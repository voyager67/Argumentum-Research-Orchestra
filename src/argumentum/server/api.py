"""Tenant-aware FastAPI service for Argumentum."""
from __future__ import annotations
import hashlib,hmac,json,os,re,secrets,shutil,tempfile,uuid
from collections.abc import Generator
from datetime import datetime,timezone
from pathlib import Path
from fastapi import Depends,FastAPI,File,Form,HTTPException,Query,UploadFile
from fastapi.responses import FileResponse,HTMLResponse
from fastapi.security import HTTPAuthorizationCredentials,HTTPBearer
from sqlalchemy import func,select,text,update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .db import get_db,get_engine
from .db_models import ApiCredential,ResearchJob,ResearchProject,Tenant
from .middleware import UploadBodyLimitMiddleware
from .queueing import enqueue_research_run,new_rq_job_id
from .recovery import reconcile_jobs,retry_run
from .schemas import *
from ..io_utils import MAX_FILES,MAX_FILE_BYTES,MAX_TOTAL_BYTES,OPTIONAL_DOCUMENTS,SUPPORTED_TEXT

ARTIFACT_ALLOWLIST={"RUN_SUMMARY.md","manuscript.md","manuscript.tex","references.bib","sources.json","research_charter.json","literature_scout.json","evidence_ledger.json","evidence_ledger.md","methodology_review.json","synthesis_map.json","figure_and_data_review.json","peer_review.md","integrity_report.json","AI_USE_DISCLOSURE.txt","run_manifest.json","RUN_FAILED.txt"}
UPLOAD_SUFFIXES=SUPPORTED_TEXT|OPTIONAL_DOCUMENTS
DEFAULT_TENANT_ID="00000000-0000-4000-8000-000000000001"
@dataclass
class Principal:
    tenant_id:str|None
    role:str
    credential_id:str|None=None
    platform_admin:bool=False

def _token_digest(value:str)->str:
    return hashlib.sha256(value.encode()).hexdigest()

def create_app(api_token:str|None=None)->FastAPI:
    from dataclasses import dataclass as _unused
    test_token=api_token
    workspace_token=os.getenv("ARGUMENTUM_API_TOKEN","")
    admin_token=os.getenv("ARGUMENTUM_ADMIN_TOKEN","")
    data_dir=Path(os.getenv("ARGUMENTUM_DATA_DIR","/data")).expanduser().resolve()
    app=FastAPI(title="Argumentum Research API",version="1.0.0",description="Tenant-scoped research workflows.")
    bearer=HTTPBearer(auto_error=False)
    def db_dep()->Generator[Session,None,None]:
        yield from get_db()
    def default_principal(session:Session)->Principal:
        tenant=session.scalar(select(Tenant).where(Tenant.slug=="default"))
        if tenant is None:
            tenant=Tenant(id=DEFAULT_TENANT_ID,name="Default workspace",slug="default",is_active=True);session.add(tenant);session.flush()
        if not tenant.is_active:raise HTTPException(403,"Default workspace is disabled")
        digest=_token_digest(workspace_token);record=session.scalar(select(ApiCredential).where(ApiCredential.token_hash==digest))
        if record:
            if record.tenant_id!=tenant.id or record.role!="owner" or not record.is_bootstrap or not record.is_active:raise HTTPException(403,"Default workspace credential is invalid")
            return Principal(tenant.id,"owner",record.id)
        session.execute(update(ApiCredential).where(ApiCredential.tenant_id==tenant.id,ApiCredential.is_bootstrap.is_(True),ApiCredential.is_active.is_(True)).values(is_active=False))
        record=ApiCredential(id=str(uuid.uuid4()),tenant_id=tenant.id,name="Default workspace owner",token_hash=digest,role="owner",is_active=True,is_bootstrap=True)
        session.add(record);session.commit();return Principal(tenant.id,"owner",record.id)
    def authenticate(raw:str,session:Session)->Principal|None:
        if (test_token and hmac.compare_digest(raw,test_token)) or (admin_token and hmac.compare_digest(raw,admin_token)):return Principal(None,"platform_admin",platform_admin=True)
        if workspace_token and hmac.compare_digest(raw,workspace_token):return default_principal(session)
        record=session.scalar(select(ApiCredential).where(ApiCredential.token_hash==_token_digest(raw),ApiCredential.is_active.is_(True)))
        if record is None:return None
        tenant=session.get(Tenant,record.tenant_id)
        if tenant is None or not tenant.is_active:return None
        record.last_used_at=datetime.now(timezone.utc);session.commit()
        return Principal(tenant.id,record.role,record.id)
    def middleware_valid(raw:str)->bool:
        if not raw:return False
        if (test_token and hmac.compare_digest(raw,test_token)) or (admin_token and hmac.compare_digest(raw,admin_token)):return True
        try:
            with get_engine().connect() as conn:
                digest=_token_digest(raw)
                if workspace_token and hmac.compare_digest(raw,workspace_token):
                    tenant=conn.execute(select(Tenant.id,Tenant.is_active).where(Tenant.slug=="default")).first()
                    if tenant is None or not tenant.is_active:return False
                    row=conn.execute(select(ApiCredential.tenant_id,ApiCredential.role,ApiCredential.is_active).where(ApiCredential.token_hash==digest)).first()
                    return row is None or (row.tenant_id==tenant.id and row.role=="owner" and row.is_active)
                return conn.execute(select(ApiCredential.id).join(Tenant,Tenant.id==ApiCredential.tenant_id).where(ApiCredential.token_hash==digest,ApiCredential.is_active.is_(True),Tenant.is_active.is_(True))).first() is not None
        except Exception:return False
    app.add_middleware(UploadBodyLimitMiddleware,max_body_bytes=MAX_TOTAL_BYTES+2*1024*1024,expected_bearer_token=test_token or "",token_validator=None if test_token else middleware_valid)
    def principal_dep(credentials:HTTPAuthorizationCredentials|None=Depends(bearer),session:Session=Depends(db_dep))->Principal:
        if credentials is None or credentials.scheme.lower()!="bearer":raise HTTPException(401,"Invalid or missing bearer token")
        if not (test_token or workspace_token or admin_token) and session.scalar(select(ApiCredential.id).where(ApiCredential.is_active.is_(True)).limit(1)) is None:raise HTTPException(503,"No API credentials are configured")
        result=authenticate(credentials.credentials,session)
        if result is None:raise HTTPException(401,"Invalid, revoked, or inactive bearer token")
        return result
    def roles(p:Principal,*allowed:str)->None:
        if not p.platform_admin and p.role not in allowed:raise HTTPException(403,"Insufficient role permissions")
    def platform(p:Principal)->None:
        if not p.platform_admin:raise HTTPException(403,"Platform administrator required")
    def owned_job(session:Session,p:Principal,rid:str)->ResearchJob|None:
        stmt=select(ResearchJob).where(ResearchJob.id==rid)
        if not p.platform_admin:stmt=stmt.where(ResearchJob.tenant_id==p.tenant_id)
        return session.scalar(stmt)
    def project_info(session:Session,row:ResearchProject)->ProjectInfo:
        count=session.scalar(select(func.count(ResearchJob.id)).where(ResearchJob.project_id==row.id)) or 0
        return ProjectInfo(project_id=row.id,name=row.name,slug=row.slug,description=row.description,status=row.status,run_count=count,created_at=row.created_at,updated_at=row.updated_at)
    def enqueue(payload:ResearchRunRequest,session:Session,tenant_id:str,has_materials:bool=False,rid:str|None=None)->ResearchRunAccepted:
        rid=rid or str(uuid.uuid4());rqid=new_rq_job_id(rid);data=payload.model_dump();pid=data.get("project_id")
        if pid and session.scalar(select(ResearchProject.id).where(ResearchProject.id==pid,ResearchProject.tenant_id==tenant_id,ResearchProject.status=="active")) is None:raise HTTPException(404,"Active project not found")
        if has_materials:data["has_materials"]=True
        session.add(ResearchJob(id=rid,tenant_id=tenant_id,project_id=pid,status="queued",request_json=data,attempts=0,rq_job_id=rqid));session.commit()
        try:enqueue_research_run(rid,data,job_id=rqid)
        except Exception as exc:
            session.execute(update(ResearchJob).where(ResearchJob.id==rid,ResearchJob.status=="queued").values(status="queue_failed",error=f"QueueUnavailable:{type(exc).__name__}",finished_at=datetime.now(timezone.utc)));session.commit()
            raise HTTPException(503,"Queue publication could not be confirmed; inspect run status before resubmitting") from exc
        return ResearchRunAccepted(run_id=rid,status="queued",status_url=f"/api/v1/runs/{rid}")
    async def save_uploads(files:list[UploadFile],rid:str)->Path:
        if not files or len(files)>MAX_FILES:raise HTTPException(413,"Invalid upload file count")
        root=data_dir/"inputs"
        if root.is_symlink():raise HTTPException(409,"Input storage cannot be a symlink")
        root.mkdir(parents=True,exist_ok=True,mode=0o700);os.chmod(root,0o700);root=root.resolve();target=root/rid
        if target.exists():raise HTTPException(409,"Input directory already exists")
        stage=Path(tempfile.mkdtemp(prefix=f".{rid}-",dir=root));total=0;names=set()
        try:
            for upload in files:
                name=upload.filename or ""
                if not name or name!=name.strip() or len(name)>180 or any(c in name for c in ("/","\\","\x00",":")) or any(ord(c)<32 for c in name):raise HTTPException(400,"Invalid filename")
                if Path(name).suffix.lower() not in UPLOAD_SUFFIXES or Path(name).name in {".",".."}:raise HTTPException(415,"Unsupported file type")
                if name.casefold() in names:raise HTTPException(400,"Duplicate filenames")
                names.add(name.casefold());size=0
                with (stage/name).open("xb") as stream:
                    while chunk:=await upload.read(65536):
                        size+=len(chunk);total+=len(chunk)
                        if size>MAX_FILE_BYTES or total>MAX_TOTAL_BYTES:raise HTTPException(413,"Upload size limit exceeded")
                        stream.write(chunk)
                os.chmod(stage/name,0o600)
                if size==0:raise HTTPException(400,"Empty upload")
            os.replace(stage,target);return target
        except Exception:
            shutil.rmtree(stage,ignore_errors=True);raise
        finally:
            for item in files:await item.close()
    @app.get("/ui",response_class=HTMLResponse,include_in_schema=False)
    def ui()->HTMLResponse:
        path=Path(__file__).parent/"static"/"index.html"
        if not path.is_file():raise HTTPException(404,"Researcher UI is not installed")
        return HTMLResponse(path.read_text(encoding="utf-8"))
    @app.get("/api/v1/session")
    def session_info(p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        if p.platform_admin:return {"role":"platform_admin","tenant_id":None,"tenant_name":None}
        tenant=session.get(Tenant,p.tenant_id)
        if tenant is None or not tenant.is_active:raise HTTPException(401,"Workspace inactive")
        return {"role":p.role,"tenant_id":tenant.id,"tenant_name":tenant.name,"tenant_slug":tenant.slug}
    @app.get("/api/v1/projects",response_model=list[ProjectInfo])
    def list_projects(p:Principal=Depends(principal_dep),session:Session=Depends(db_dep),include_archived:bool=False):
        if p.tenant_id is None:raise HTTPException(400,"Workspace context required")
        stmt=select(ResearchProject).where(ResearchProject.tenant_id==p.tenant_id)
        if not include_archived:stmt=stmt.where(ResearchProject.status=="active")
        return [project_info(session,row) for row in session.scalars(stmt.order_by(ResearchProject.updated_at.desc())).all()]
    @app.post("/api/v1/projects",response_model=ProjectInfo,status_code=201)
    def create_project(payload:ProjectCreateRequest,p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        roles(p,"owner","admin","researcher")
        if p.tenant_id is None:raise HTTPException(400,"Workspace context required")
        slug=payload.slug or re.sub(r"[^a-z0-9]+","-",payload.name.lower()).strip("-")[:100]
        row=ResearchProject(id=str(uuid.uuid4()),tenant_id=p.tenant_id,name=payload.name,slug=slug,description=payload.description,status="active")
        session.add(row)
        try:session.commit()
        except IntegrityError as exc:session.rollback();raise HTTPException(409,"Project slug already exists") from exc
        session.refresh(row);return project_info(session,row)
    @app.patch("/api/v1/projects/{pid}",response_model=ProjectInfo)
    def update_project(pid:str,payload:ProjectUpdateRequest,p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        roles(p,"owner","admin","researcher")
        row=session.scalar(select(ResearchProject).where(ResearchProject.id==pid,ResearchProject.tenant_id==p.tenant_id))
        if row is None:raise HTTPException(404,"Project not found")
        for key,value in payload.model_dump(exclude_unset=True).items():
            if value is not None:setattr(row,key,value)
        row.updated_at=datetime.now(timezone.utc);session.commit();session.refresh(row);return project_info(session,row)
    @app.delete("/api/v1/projects/{pid}",response_model=ProjectInfo)
    def archive_project(pid:str,p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        roles(p,"owner","admin")
        row=session.scalar(select(ResearchProject).where(ResearchProject.id==pid,ResearchProject.tenant_id==p.tenant_id))
        if row is None:raise HTTPException(404,"Project not found")
        row.status="archived";row.updated_at=datetime.now(timezone.utc);session.commit();session.refresh(row);return project_info(session,row)
    @app.get("/health/live")
    def live():return {"status":"alive"}
    @app.get("/health/ready")
    def ready():
        try:
            with get_engine().connect() as conn:conn.execute(text("SELECT 1"))
            from redis import Redis
            client=Redis.from_url(os.getenv("REDIS_URL","redis://localhost:6379/0"),socket_connect_timeout=3,socket_timeout=3)
            try:client.ping()
            finally:client.close()
            return {"status":"ready"}
        except Exception as exc:raise HTTPException(503,"Database or queue unavailable") from exc
    @app.post("/api/v1/runs",response_model=ResearchRunAccepted,status_code=202)
    def submit_run(payload:ResearchRunRequest,p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        roles(p,"owner","admin","researcher")
        if p.tenant_id is None:raise HTTPException(400,"Use a workspace credential")
        return enqueue(payload,session,p.tenant_id)
    @app.post("/api/v1/runs/with-materials",response_model=ResearchRunAccepted,status_code=202)
    async def submit_materials(request_json:str=Form(...,max_length=12000),files:list[UploadFile]=File(...),p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        roles(p,"owner","admin","researcher")
        if p.tenant_id is None:raise HTTPException(400,"Workspace context required")
        try:payload=ResearchRunRequest.model_validate_json(request_json)
        except Exception as exc:raise HTTPException(422,"Invalid request_json") from exc
        rid=str(uuid.uuid4());input_dir=None
        try:
            input_dir=await save_uploads(files,rid);return enqueue(payload,session,p.tenant_id,True,rid)
        except Exception:
            session.rollback()
            if input_dir is not None and session.get(ResearchJob,rid) is None:shutil.rmtree(input_dir,ignore_errors=True)
            raise
    @app.get("/api/v1/runs",response_model=list[ResearchRunStatus])
    def list_runs(p:Principal=Depends(principal_dep),session:Session=Depends(db_dep),limit:int=Query(25,ge=1,le=100),project_id:str|None=None):
        stmt=select(ResearchJob).order_by(ResearchJob.created_at.desc()).limit(limit)
        if not p.platform_admin:stmt=stmt.where(ResearchJob.tenant_id==p.tenant_id)
        if project_id:stmt=stmt.where(ResearchJob.project_id==project_id)
        rows=session.scalars(stmt).all()
        return [ResearchRunStatus(run_id=r.id,status=r.status,project_id=r.project_id,created_at=r.created_at,started_at=r.started_at,finished_at=r.finished_at,attempts=r.attempts,error=r.error,artifacts_url=f"/api/v1/runs/{r.id}/artifacts" if r.status.startswith("completed") or r.status=="failed" else None) for r in rows]
    @app.get("/api/v1/runs/{rid}",response_model=ResearchRunStatus)
    def get_run(rid:str,p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        row=session.scalar(select(ResearchJob).where(ResearchJob.id==rid,True if p.platform_admin else ResearchJob.tenant_id==p.tenant_id))
        if row is None:raise HTTPException(404,"Run not found")
        return ResearchRunStatus(run_id=row.id,status=row.status,project_id=row.project_id,created_at=row.created_at,started_at=row.started_at,finished_at=row.finished_at,attempts=row.attempts,error=row.error)
    @app.post("/api/v1/runs/{rid}/retry",response_model=RetryRunResponse)
    def retry_endpoint(rid:str,p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        roles(p,"owner","admin")
        if owned_job(session,p,rid) is None:raise HTTPException(404,"Run not found")
        result=retry_run(rid)
        if result["status"] in {"not_found","not_retryable"}:raise HTTPException(409,"Run is not retryable")
        if result["status"]=="queue_failed":raise HTTPException(503,"Retry queue unavailable")
        return RetryRunResponse(**result)
    @app.post("/api/v1/maintenance/reconcile",response_model=ReconciliationResponse)
    def reconcile(p:Principal=Depends(principal_dep),limit:int=Query(50,ge=1,le=200),stale_after_seconds:int=Query(1800,ge=60,le=86400)):
        platform(p);return ReconciliationResponse(**reconcile_jobs(limit=limit,stale_after_seconds=stale_after_seconds))
    @app.get("/api/v1/runs/{rid}/artifacts",response_model=list[ArtifactInfo])
    def artifacts(rid:str,p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        if owned_job(session,p,rid) is None:raise HTTPException(404,"Run not found")
        root=(data_dir/"runs"/str(uuid.UUID(rid))).resolve()
        if root.parent!=(data_dir/"runs").resolve() or not root.is_dir():return []
        return [ArtifactInfo(name=x.name,size_bytes=x.stat().st_size,download_url=f"/api/v1/runs/{rid}/artifacts/{x.name}") for x in root.iterdir() if x.is_file() and not x.is_symlink() and x.name in ARTIFACT_ALLOWLIST]
    @app.get("/api/v1/runs/{rid}/artifacts/{filename}")
    def download(rid:str,filename:str,p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        if owned_job(session,p,rid) is None or filename not in ARTIFACT_ALLOWLIST or Path(filename).name!=filename:raise HTTPException(404,"Artifact not found")
        root=(data_dir/"runs"/str(uuid.UUID(rid))).resolve();path=root/filename
        if not path.is_file() or path.is_symlink() or path.resolve().parent!=root:raise HTTPException(404,"Artifact not found")
        return FileResponse(path,filename=filename)
    @app.post("/api/v1/admin/tenants",response_model=TenantCreated,status_code=201)
    def create_tenant(payload:TenantCreateRequest,p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        platform(p)
        if session.scalar(select(Tenant.id).where(Tenant.slug==payload.slug)):raise HTTPException(409,"Tenant slug already exists")
        tid,cid=str(uuid.uuid4()),str(uuid.uuid4());raw=secrets.token_urlsafe(40)
        tenant=Tenant(id=tid,name=payload.name,slug=payload.slug,is_active=True);credential=ApiCredential(id=cid,tenant_id=tid,name="Initial owner",token_hash=_token_digest(raw),role="owner",is_active=True)
        session.add_all([tenant,credential]);session.commit()
        return TenantCreated(tenant_id=tid,name=tenant.name,slug=tenant.slug,owner_credential_id=cid,owner_token=raw)
    @app.get("/api/v1/admin/tenants",response_model=list[TenantAdminInfo])
    def tenants(p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        platform(p);return [TenantAdminInfo(tenant_id=t.id,name=t.name,slug=t.slug,is_active=t.is_active,created_at=t.created_at) for t in session.scalars(select(Tenant)).all()]
    @app.patch("/api/v1/admin/tenants/{tid}/active",response_model=TenantAdminInfo)
    def activate_tenant(tid:str,payload:TenantActivationRequest,p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        platform(p);row=session.get(Tenant,tid)
        if row is None:raise HTTPException(404,"Tenant not found")
        row.is_active=payload.is_active;session.commit()
        return TenantAdminInfo(tenant_id=row.id,name=row.name,slug=row.slug,is_active=row.is_active,created_at=row.created_at)
    @app.get("/api/v1/tenant",response_model=TenantInfo)
    def tenant_info(p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        if p.tenant_id is None:raise HTTPException(400,"Platform admins have no tenant")
        t=session.get(Tenant,p.tenant_id)
        if t is None or not t.is_active:raise HTTPException(404,"Tenant not found")
        return TenantInfo(tenant_id=t.id,name=t.name,slug=t.slug,role=p.role)
    @app.post("/api/v1/tenant/credentials",response_model=CredentialCreated,status_code=201)
    def create_credential(payload:CredentialCreateRequest,p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        roles(p,"owner","admin")
        if p.tenant_id is None:raise HTTPException(400,"Workspace context required")
        if p.role=="admin" and payload.role=="admin":raise HTTPException(403,"Only owners may issue admins")
        raw=secrets.token_urlsafe(40);row=ApiCredential(id=str(uuid.uuid4()),tenant_id=p.tenant_id,name=payload.name,token_hash=_token_digest(raw),role=payload.role,is_active=True)
        session.add(row);session.commit();return CredentialCreated(credential_id=row.id,name=row.name,role=row.role,token=raw,created_at=row.created_at)
    @app.get("/api/v1/tenant/credentials",response_model=list[CredentialInfo])
    def credentials(p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        roles(p,"owner","admin")
        if p.tenant_id is None:raise HTTPException(400,"Workspace context required")
        return [CredentialInfo(credential_id=r.id,name=r.name,role=r.role,is_active=r.is_active,created_at=r.created_at,last_used_at=r.last_used_at) for r in session.scalars(select(ApiCredential).where(ApiCredential.tenant_id==p.tenant_id)).all()]
    @app.delete("/api/v1/tenant/credentials/{cid}")
    def revoke(cid:str,p:Principal=Depends(principal_dep),session:Session=Depends(db_dep)):
        roles(p,"owner","admin")
        if cid==p.credential_id:raise HTTPException(409,"A credential cannot revoke itself")
        row=session.scalar(select(ApiCredential).where(ApiCredential.id==cid,ApiCredential.tenant_id==p.tenant_id))
        if row is None:raise HTTPException(404,"Credential not found")
        if p.role=="admin" and row.role in {"owner","admin"}:raise HTTPException(403,"Admins cannot revoke owner/admin credentials")
        row.is_active=False;session.commit();return {"revoked":True}

    @app.post("/api/v1/experiments", response_model=ExperimentAccepted, status_code=202)
    def submit_experiment(payload: ExperimentExecutionRequest, p: Principal = Depends(principal_dep)) -> ExperimentAccepted:
        roles(p, "owner", "admin")
        if p.tenant_id is None or payload.human_approved is not True:
            raise HTTPException(403, "Workspace owner/admin and explicit human approval required")
        root = data_dir / "sandbox"
        folders = [root / name for name in ("inbox", "processing", "results")]
        if root.is_symlink() or any(folder.is_symlink() for folder in folders):
            raise HTTPException(409, "Sandbox storage cannot be a symbolic link")
        for folder in folders:
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(folder, 0o700)
        pending = 0
        for folder in folders[:2]:
            for path in folder.glob("*.json"):
                if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
                    continue
                try:
                    pending += json.loads(path.read_text(encoding="utf-8")).get("tenant_id") == p.tenant_id
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
        if pending >= 5:
            raise HTTPException(429, "Workspace experiment queue limit reached")
        experiment_id = str(uuid.uuid4())
        submitted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        record = {
            "experiment_id": experiment_id, "tenant_id": p.tenant_id, "requested_by": p.credential_id,
            "purpose": payload.purpose, "code": payload.code, "timeout_seconds": payload.timeout_seconds,
            "human_approved": True, "submitted_at": submitted_at,
        }
        target = folders[0] / f"{experiment_id}.json"
        temporary = folders[0] / f".{experiment_id}.{secrets.token_hex(8)}.tmp"
        try:
            temporary.write_text(json.dumps(record), encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise HTTPException(503, "Experiment queue is not writable") from exc
        return ExperimentAccepted(experiment_id=experiment_id, status="queued",
                                  status_url=f"/api/v1/experiments/{experiment_id}", approval_recorded=True)

    @app.get("/api/v1/experiments/{experiment_id}", response_model=ExperimentStatus)
    def get_experiment(experiment_id: str, p: Principal = Depends(principal_dep)) -> ExperimentStatus:
        try:
            canonical_id = str(uuid.UUID(experiment_id))
        except ValueError as exc:
            raise HTTPException(404, "Experiment not found") from exc
        root = data_dir / "sandbox"
        if root.is_symlink() or any((root / folder).is_symlink() for folder in ("results", "processing", "inbox")):
            raise HTTPException(404, "Experiment not found")
        locations = [(root / "results" / f"{canonical_id}.json", "result"),
                     (root / "processing" / f"{canonical_id}.json", "processing"),
                     (root / "inbox" / f"{canonical_id}.json", "queued")]
        record = None
        inferred = "queued"
        for path, state in locations:
            if path.is_symlink():
                continue
            if path.is_file():
                try:
                    if path.stat().st_size > 131072:
                        raise ValueError("status file too large")
                    record = json.loads(path.read_text(encoding="utf-8"))
                    inferred = state
                    break
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    raise HTTPException(503, "Experiment status unavailable") from exc
        if record is None or (not p.platform_admin and record.get("tenant_id") != p.tenant_id):
            raise HTTPException(404, "Experiment not found")
        state = record.get("status", "running" if inferred == "processing" else inferred)
        if state not in {"queued", "running", "succeeded", "failed", "blocked"}:
            state = "blocked"
        return ExperimentStatus(
            experiment_id=canonical_id, status=state, purpose=str(record.get("purpose", ""))[:500],
            submitted_at=record.get("submitted_at"), finished_at=record.get("finished_at"),
            exit_code=record.get("exit_code"), elapsed_seconds=record.get("elapsed_seconds"),
            stdout=str(record.get("stdout", ""))[:16384], stderr=str(record.get("stderr", ""))[:16384],
            isolation=record.get("isolation"),
        )
    return app

app=create_app()
