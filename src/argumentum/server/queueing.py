"""Redis Queue integration with bounded automatic retries and recoverable job IDs."""

from __future__ import annotations

import os
import uuid
from typing import Any


def new_rq_job_id(run_id: str, *, recovery: bool = False) -> str:
    suffix = uuid.uuid4().hex[: 12 if recovery else 8]
    return f"{run_id}-{suffix}"


def enqueue_research_run(
    run_id: str, payload: dict[str, Any], *, job_id: str | None = None, recovery: bool = False
) -> str:
    try:
        from redis import Redis
        from rq import Callback, Queue, Retry
    except ImportError as exc:
        raise RuntimeError("Self-hosted queue dependencies are missing. Install argumentum[server].") from exc
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    connection = Redis.from_url(redis_url, socket_connect_timeout=5, socket_timeout=5)
    try:
        connection.ping()
        queue = Queue(
            "argumentum", connection=connection, default_timeout=int(os.getenv("ARGUMENTUM_JOB_TIMEOUT", "7200"))
        )
        retries = max(0, min(int(os.getenv("ARGUMENTUM_JOB_RETRIES", "2")), 5))
        retry = Retry(max=retries, interval=[15, 60, 180][:retries]) if retries else None
        reserved_id = job_id or new_rq_job_id(run_id, recovery=recovery)
        job = queue.enqueue(
            "argumentum.server.worker.execute_research_run",
            run_id,
            payload,
            job_id=reserved_id,
            retry=retry,
            result_ttl=86_400,
            failure_ttl=604_800,
            on_failure=Callback("argumentum.server.worker.mark_research_run_failed"),
        )
        return str(job.id)
    finally:
        connection.close()
