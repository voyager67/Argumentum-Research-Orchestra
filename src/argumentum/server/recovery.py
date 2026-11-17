"""Reconcile durable database jobs with Redis Queue after partial failures or worker crashes."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import and_, or_, select, update

from .db import get_session_factory
from .db_models import ResearchJob
from .queueing import enqueue_research_run, new_rq_job_id

ACTIVE_RQ_STATES = {"queued", "started", "deferred", "scheduled", "busy", "rate_limited", "ready_to_enqueue"}


class RQStateLookupError(RuntimeError):
    """RQ state cannot be read safely."""


def _rq_state(job: Any) -> str | None:
    if job is None:
        return None
    try:
        state = job.get_status(refresh=True)
        if state is None:
            raise ValueError("RQ job state is missing")
        return str(getattr(state, "value", state)).lower()
    except Exception as exc:
        raise RQStateLookupError("Unable to read existing RQ job state") from exc
    finally:
        connection = getattr(job, "connection", None)
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass


def _completed_artifact_status(run_id: str) -> tuple[str, str] | None:
    data_root = Path(os.getenv("ARGUMENTUM_DATA_DIR", "/data")).expanduser().resolve()
    runs_root = (data_root / "runs").resolve()
    run_root = runs_root / run_id
    if run_root.parent != runs_root or not run_root.is_dir() or run_root.is_symlink():
        return None
    manifest_path = run_root / "run_manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    state = manifest.get("status")
    return (state, str(run_root)) if state in {"completed", "completed_with_warnings"} else None


def _reserve_reconciliation(
    *, run_id: str, old_status: str, stale_before: datetime, planned_rq_id: str, now: datetime
) -> bool:
    conditions = [ResearchJob.id == run_id, ResearchJob.status == old_status]
    if old_status in {"running", "reconciling"}:
        conditions.append(or_(ResearchJob.heartbeat_at.is_(None), ResearchJob.heartbeat_at < stale_before))
    factory = get_session_factory()
    with factory() as session:
        result = session.execute(
            update(ResearchJob)
            .where(*conditions)
            .values(status="reconciling", heartbeat_at=now, rq_job_id=planned_rq_id)
        )
        session.commit()
        return result.rowcount == 1


def reconcile_jobs(*, limit: int = 50, stale_after_seconds: int = 1800) -> dict[str, Any]:
    now = datetime.now(UTC)
    stale_before = now - timedelta(seconds=stale_after_seconds)
    factory = get_session_factory()
    with factory() as session:
        candidates = session.scalars(
            select(ResearchJob)
            .where(
                or_(
                    ResearchJob.status.in_(["queue_failed", "retrying", "queued"]),
                    and_(
                        ResearchJob.status.in_(["running", "reconciling"]),
                        or_(ResearchJob.heartbeat_at.is_(None), ResearchJob.heartbeat_at < stale_before),
                    ),
                )
            )
            .order_by(ResearchJob.created_at.asc())
            .limit(limit)
        ).all()
        snapshots = [(row.id, row.status, dict(row.request_json), row.rq_job_id, row.attempts) for row in candidates]
    report: dict[str, Any] = {"examined": len(snapshots), "requeued": [], "active": [], "skipped": [], "failed": []}
    max_attempts = 1 + max(0, min(int(os.getenv("ARGUMENTUM_JOB_RETRIES", "2")), 5))
    for run_id, old_status, payload, rq_job_id, attempts in snapshots:
        recovered_artifact = _completed_artifact_status(run_id)
        if recovered_artifact:
            recovered_status, output_path = recovered_artifact
            with factory() as session:
                session.execute(
                    update(ResearchJob)
                    .where(ResearchJob.id == run_id, ResearchJob.status == old_status)
                    .values(
                        status=recovered_status, output_path=output_path, finished_at=now, heartbeat_at=None, error=None
                    )
                )
                session.commit()
            report["skipped"].append({"run_id": run_id, "reason": "completed_artifacts_reconciled"})
            continue
        state: str | None = None
        if rq_job_id:
            try:
                state = _rq_state(_fetch_existing_job_by_id(rq_job_id))
            except Exception as exc:
                report["failed"].append({"run_id": run_id, "error": type(exc).__name__})
                continue
            if state in ACTIVE_RQ_STATES:
                report["active"].append(run_id)
                continue
        if old_status in {"running", "retrying", "reconciling", "queued"} and attempts >= max_attempts:
            with factory() as session:
                session.execute(
                    update(ResearchJob)
                    .where(ResearchJob.id == run_id, ResearchJob.status == old_status)
                    .values(status="failed", error="RetryLimitReached", finished_at=now, heartbeat_at=None)
                )
                session.commit()
            report["skipped"].append({"run_id": run_id, "reason": "retry_limit_reached"})
            continue
        planned_rq_id = rq_job_id if rq_job_id and state is None else new_rq_job_id(run_id, recovery=True)
        if not _reserve_reconciliation(
            run_id=run_id, old_status=old_status, stale_before=stale_before, planned_rq_id=planned_rq_id, now=now
        ):
            report["skipped"].append({"run_id": run_id, "reason": "claimed_by_another_reconciler"})
            continue
        try:
            published_id = enqueue_research_run(run_id, payload, job_id=planned_rq_id, recovery=True)
            with factory() as session:
                session.execute(
                    update(ResearchJob)
                    .where(ResearchJob.id == run_id, ResearchJob.status == "reconciling")
                    .values(status="queued", rq_job_id=published_id, error=None, finished_at=None, heartbeat_at=None)
                )
                session.commit()
            report["requeued"].append({"run_id": run_id, "rq_job_id": published_id})
        except Exception as exc:
            with factory() as session:
                session.execute(
                    update(ResearchJob)
                    .where(ResearchJob.id == run_id, ResearchJob.status == "reconciling")
                    .values(
                        status="queue_failed",
                        rq_job_id=planned_rq_id,
                        error=f"QueueUnavailable:{type(exc).__name__}",
                        finished_at=now,
                        heartbeat_at=None,
                    )
                )
                session.commit()
            report["failed"].append({"run_id": run_id, "error": type(exc).__name__})
    return report


def _fetch_existing_job_by_id(job_id: str) -> Any | None:
    try:
        from redis import Redis
        from rq import Queue
    except ImportError as exc:
        raise RuntimeError("Self-hosted queue dependencies are missing. Install argumentum[server].") from exc
    connection = Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"), socket_connect_timeout=5, socket_timeout=5
    )
    try:
        connection.ping()
        queue = Queue("argumentum", connection=connection)
        job = queue.fetch_job(job_id)
        if job is None:
            connection.close()
        return job
    except Exception:
        connection.close()
        raise


def retry_run(run_id: str) -> dict[str, Any]:
    now = datetime.now(UTC)
    factory = get_session_factory()
    recovered_artifact = _completed_artifact_status(run_id)
    if recovered_artifact:
        recovered_status, output_path = recovered_artifact
        with factory() as session:
            session.execute(
                update(ResearchJob)
                .where(ResearchJob.id == run_id)
                .values(
                    status=recovered_status, output_path=output_path, finished_at=now, heartbeat_at=None, error=None
                )
            )
            session.commit()
        return {"status": recovered_status, "run_id": run_id}
    with factory() as session:
        record = session.get(ResearchJob, run_id)
        if record is None:
            return {"status": "not_found", "run_id": run_id}
        if record.status not in {"failed", "queue_failed"}:
            return {"status": "not_retryable", "run_id": run_id, "current_status": record.status}
        payload = dict(record.request_json)
        prior_rq_id = record.rq_job_id
    if prior_rq_id:
        try:
            active_state = _rq_state(_fetch_existing_job_by_id(prior_rq_id))
        except Exception as exc:
            return {"status": "queue_failed", "run_id": run_id, "error": type(exc).__name__}
        if active_state in ACTIVE_RQ_STATES:
            return {"status": "already_active", "run_id": run_id, "current_status": active_state}
    planned_rq_id = new_rq_job_id(run_id, recovery=True)
    with factory() as session:
        record = session.get(ResearchJob, run_id)
        if record is None:
            return {"status": "not_found", "run_id": run_id}
        if record.status not in {"failed", "queue_failed"}:
            return {"status": "not_retryable", "run_id": run_id, "current_status": record.status}
        expected_status = record.status
        claim = session.execute(
            update(ResearchJob)
            .where(ResearchJob.id == run_id, ResearchJob.status == expected_status)
            .values(status="reconciling", heartbeat_at=now, attempts=0, rq_job_id=planned_rq_id)
        )
        session.commit()
        if claim.rowcount != 1:
            return {"status": "claimed_by_another_request", "run_id": run_id}
    try:
        published_id = enqueue_research_run(run_id, payload, job_id=planned_rq_id, recovery=True)
        with factory() as session:
            session.execute(
                update(ResearchJob)
                .where(ResearchJob.id == run_id, ResearchJob.status == "reconciling")
                .values(status="queued", rq_job_id=published_id, error=None, finished_at=None, heartbeat_at=None)
            )
            session.commit()
        return {"status": "queued", "run_id": run_id, "rq_job_id": published_id}
    except Exception as exc:
        with factory() as session:
            session.execute(
                update(ResearchJob)
                .where(ResearchJob.id == run_id, ResearchJob.status == "reconciling")
                .values(
                    status="queue_failed",
                    rq_job_id=planned_rq_id,
                    error=f"QueueUnavailable:{type(exc).__name__}",
                    finished_at=now,
                    heartbeat_at=None,
                )
            )
            session.commit()
        return {"status": "queue_failed", "run_id": run_id, "error": type(exc).__name__}
