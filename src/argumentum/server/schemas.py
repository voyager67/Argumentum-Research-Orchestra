"""HTTP request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ResearchQuery = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=240)]
ResearchTopic = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=500)]
ResearchQuestion = Annotated[str, StringConstraints(strip_whitespace=True, min_length=10, max_length=2_000)]

class ResearchRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: ResearchTopic
    question: ResearchQuestion
    discipline: Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)] = "Interdisciplinary"
    study_type: Annotated[str, StringConstraints(strip_whitespace=True, max_length=80)] = "auto"
    audience: Annotated[str, StringConstraints(strip_whitespace=True, max_length=160)] = "graduate researchers"
    source_limit: int = Field(default=24, ge=1, le=100)
    queries: list[ResearchQuery] = Field(default_factory=list, max_length=6)
    demo_mode: bool = False
    project_id: str | None = None

class ResearchRunAccepted(BaseModel):
    run_id: str
    status: Literal["queued"]
    status_url: str

class ResearchRunStatus(BaseModel):
    run_id: str
    status: str
    project_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    attempts: int
    error: str | None = None
    artifacts_url: str | None = None

class ArtifactInfo(BaseModel):
    name: str
    size_bytes: int
    download_url: str

class RetryRunResponse(BaseModel):
    status: str
    run_id: str
    rq_job_id: str | None = None
    current_status: str | None = None
    error: str | None = None

class ReconciliationResponse(BaseModel):
    examined: int
    requeued: list[dict[str, str]]
    active: list[str]
    skipped: list[dict[str, str]]
    failed: list[dict[str, str]]

class TenantCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
    slug: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$", max_length=80)]

class TenantActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_active: bool

class TenantCreated(BaseModel):
    tenant_id: str
    name: str
    slug: str
    owner_credential_id: str
    owner_token: str
    role: str = "owner"

class CredentialCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
    role: Literal["admin", "researcher", "viewer"] = "researcher"

class CredentialCreated(BaseModel):
    credential_id: str
    name: str
    role: str
    token: str
    created_at: datetime

class CredentialInfo(BaseModel):
    credential_id: str
    name: str
    role: str
    is_active: bool
    created_at: datetime
    last_used_at: datetime | None = None

class TenantAdminInfo(BaseModel):
    tenant_id: str
    name: str
    slug: str
    is_active: bool
    created_at: datetime

class TenantInfo(BaseModel):
    tenant_id: str
    name: str
    slug: str
    role: str

class ExperimentExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    purpose: Annotated[str, StringConstraints(strip_whitespace=True, min_length=8, max_length=500)]
    code: Annotated[str, StringConstraints(min_length=1, max_length=32_768)]
    timeout_seconds: int = Field(default=10, ge=1, le=30)
    human_approved: Literal[True]

class ExperimentAccepted(BaseModel):
    experiment_id: str
    status: Literal["queued"]
    status_url: str
    approval_recorded: bool

class ExperimentStatus(BaseModel):
    experiment_id: str
    status: Literal["queued", "running", "succeeded", "failed", "blocked"]
    purpose: str
    submitted_at: datetime
    finished_at: datetime | None = None
    exit_code: int | None = None
    elapsed_seconds: float | None = None
    stdout: str = ""
    stderr: str = ""
    isolation: str | None = None

class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)]
    slug: Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9](?:[a-z0-9-]{0,98}[a-z0-9])?$", max_length=100)] | None = None
    description: Annotated[str, StringConstraints(max_length=4_000)] = ""

class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=160)] | None = None
    description: Annotated[str, StringConstraints(max_length=4_000)] | None = None
    status: Literal["active", "archived"] | None = None

class ProjectInfo(BaseModel):
    project_id: str
    name: str
    slug: str
    description: str
    status: Literal["active", "archived"]
    run_count: int = 0
    created_at: datetime
    updated_at: datetime
