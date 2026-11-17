"""RQ worker entry point with database claiming, heartbeat leases and safe retry state."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import update

from ..config import Settings
from ..models import ResearchRequest
from ..pipeline import ResearchPipeline
from ..providers import DemoProvider, OpenAICompatibleProvider
from .db import get_session_factory
from .db_models import ResearchJob

LOGGER = logging.getLogger("argumentum.worker")

def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

def _heartbeat_loop(run_id: str, stop: threading.Event, interval: int = 30) -> None:
    factory = get_session_factory()
    while not stop.wait(interval):
        try:
            with factory() as session:
                session.execute(update(ResearchJob).where(ResearchJob.id == run_id, ResearchJob.status == "running").values(heartbeat_at=_utc_now()))
                session.commit()
        except Exception as exc:
            LOGGER.warning("Heartbeat update failed for run %s (%s)", run_id, type(exc).__name__)

def _move_attempt_to_archive(staging: Path, data_root: Path, run_id: str, attempt: int) -> None:
    if not staging.exists():
        return
    archive = data_root / "attempts" / run_id / f"attempt-{attempt:03d}"
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        archive = archive.with_name(f"{archive.name}-{_utc_now().strftime('%Y%m%dT%H%M%S%fZ')}")
    shutil.move(str(staging), str(archive))

def execute_research_run(run_id: str, payload: dict[str, Any]) -> dict[str, str]:
    factory = get_session_factory()
    now = _utc_now()
    with factory() as session:
        record = session.get(ResearchJob, run_id)
        if record is None:
            raise RuntimeError("Research run does not exist in the database")
        if record.status in {"completed", "completed_with_warnings"}:
            return {"run_id": run_id, "status": record.status}
        claim = session.execute(update(ResearchJob).where(
            ResearchJob.id == run_id,
            ResearchJob.status.in_(["queued", "retrying", "queue_failed", "reconciling"]),
        ).values(status="running", started_at=now, heartbeat_at=now, attempts=ResearchJob.attempts + 1, error=None, finished_at=None))
        session.commit()
        if claim.rowcount != 1:
            current = session.get(ResearchJob, run_id)
            state = current.status if current else "missing"
            if state in {"running", "completed", "completed_with_warnings"}:
                return {"run_id": run_id, "status": "already_running" if state == "running" else state}
            return {"run_id": run_id, "status": state}
        record = session.get(ResearchJob, run_id)
        attempt = int(record.attempts if record else 1)

    data_root = Path(os.getenv("ARGUMENTUM_DATA_DIR", "/data")).expanduser().resolve()
    data_root.mkdir(parents=True, exist_ok=True)
    working_root = data_root / "working"
    working_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{run_id}-{attempt}-", dir=working_root)) / "artifacts"
    stop_heartbeat = threading.Event()
    heartbeat = threading.Thread(target=_heartbeat_loop, args=(run_id, stop_heartbeat), daemon=True)
    heartbeat.start()
    try:
        settings = Settings.from_env()
        demo_mode = bool(payload.get("demo_mode", False))
        provider = DemoProvider() if demo_mode else OpenAICompatibleProvider(settings)
        request = ResearchRequest(
            topic=str(payload["topic"]), research_question=str(payload["question"]),
            discipline=str(payload.get("discipline", "Interdisciplinary")), study_type=str(payload.get("study_type", "auto")),
            audience=str(payload.get("audience", "graduate researchers")), source_limit=int(payload.get("source_limit", 24)),
            search_queries=tuple(str(item) for item in payload.get("queries", [])),
        )
        input_dir = None
        if payload.get("has_materials"):
            input_root = (data_root / "inputs").resolve()
            input_dir = input_root / run_id
            if input_dir.parent != input_root or input_dir.is_symlink() or not input_dir.is_dir():
                raise FileNotFoundError("Uploaded research materials are missing or outside the run input directory")
        result_path = ResearchPipeline(provider, settings, demo_mode=demo_mode).run(request, staging, input_dir=input_dir)
        manifest = result_path / "run_manifest.json"
        manifest_status = "completed_with_warnings"
        if manifest.is_file():
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
            manifest_status = str(manifest_data.get("status", manifest_status))
        status_value = "completed_with_warnings" if manifest_status == "completed_with_warnings" else "completed"
        final_path = data_root / "runs" / run_id
        final_path.parent.mkdir(parents=True, exist_ok=True)
        if final_path.exists():
            if any(final_path.iterdir()):
                raise FileExistsError("A non-empty artifact directory already exists; refusing to overwrite it")
            final_path.rmdir()
        os.replace(result_path, final_path)
        result_path.parent.rmdir()
        with factory() as session:
            session.execute(update(ResearchJob).where(ResearchJob.id == run_id, ResearchJob.status == "running").values(
                status=status_value, output_path=str(final_path), finished_at=_utc_now(), heartbeat_at=None, error=None))
            session.commit()
        return {"run_id": run_id, "status": status_value, "output_path": str(final_path)}
    except Exception as exc:
        max_retries = max(0, min(int(os.getenv("ARGUMENTUM_JOB_RETRIES", "2")), 5))
        retry_pending = attempt <= max_retries
        safe_error = f"{type(exc).__name__}: run attempt {'will be retried' if retry_pending else 'failed after retries'}; inspect restricted worker logs"
        with factory() as session:
            session.execute(update(ResearchJob).where(ResearchJob.id == run_id, ResearchJob.status == "running").values(
                status="retrying" if retry_pending else "failed", error=safe_error, finished_at=None if retry_pending else _utc_now(), heartbeat_at=None))
            session.commit()
        try:
            archived_source = result_path if "result_path" in locals() else (staging if staging.exists() else staging.parent)
            _move_attempt_to_archive(archived_source, data_root, run_id, attempt)
            if staging.parent.exists() and staging.parent != archived_source:
                staging.parent.rmdir()
            elif archived_source == staging and staging.parent.exists():
                staging.parent.rmdir()
        except OSError as archive_exc:
            LOGGER.warning("Could not archive failed run %s (%s)", run_id, type(archive_exc).__name__)
        LOGGER.error("Research run %s failed on attempt %s (%s)", run_id, attempt, type(exc).__name__)
        raise
    finally:
        stop_heartbeat.set()
        heartbeat.join(timeout=2)

def mark_research_run_failed(job: Any, connection: Any, exception_type: Any, exception_value: Any, traceback: Any) -> None:
    args = getattr(job, "args", ())
    if not args:
        return
    run_id = str(args[0])
    factory = get_session_factory()
    error_type = getattr(exception_type, "__name__", "WorkerError")
    with factory() as session:
        record = session.get(ResearchJob, run_id)
        if record and record.status not in {"completed", "completed_with_warnings"}:
            record.status = "failed"
            record.error = f"{error_type}: worker exhausted automatic retries; inspect restricted worker logs"
            record.finished_at = _utc_now()
            record.heartbeat_at = None
            session.commit()
