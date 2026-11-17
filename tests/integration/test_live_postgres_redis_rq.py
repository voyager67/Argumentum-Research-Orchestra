"""Opt-in real PostgreSQL + Redis/RQ integration smoke test.

Run with ARGUMENTUM_LIVE_INTEGRATION=1 and reachable DATABASE_URL/REDIS_URL.
The CI workflow provides disposable service containers for this test.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import select

from alembic import command
from argumentum.server.db import get_engine, get_session_factory
from argumentum.server.db_models import ResearchJob, Tenant
from argumentum.server.queueing import enqueue_research_run, new_rq_job_id

pytestmark = pytest.mark.skipif(
    os.getenv("ARGUMENTUM_LIVE_INTEGRATION") != "1",
    reason="Set ARGUMENTUM_LIVE_INTEGRATION=1 with disposable PostgreSQL and Redis services",
)


def test_live_postgres_redis_rq_completes_offline_demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    redis_module = pytest.importorskip("redis", reason="Install the server extra for Redis/RQ live tests")
    rq_module = pytest.importorskip("rq", reason="Install the server extra for Redis/RQ live tests")
    Redis = redis_module.Redis
    Job = __import__("rq.job", fromlist=["Job"]).Job
    Queue = rq_module.Queue
    SimpleWorker = rq_module.SimpleWorker
    database_url = os.environ["DATABASE_URL"]
    redis_url = os.environ["REDIS_URL"]
    data_dir = tmp_path / "argumentum-data"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("REDIS_URL", redis_url)
    monkeypatch.setenv("ARGUMENTUM_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ARGUMENTUM_JOB_RETRIES", "0")
    monkeypatch.setenv("ARGUMENTUM_TIMEOUT_SECONDS", "30")
    get_engine.cache_clear()

    project_root = Path(__file__).resolve().parents[2]
    command.upgrade(Config(str(project_root / "alembic.ini")), "head")

    redis = Redis.from_url(redis_url)
    redis.flushdb()  # The CI service uses a dedicated database for this job.
    try:
        factory = get_session_factory()
        with factory() as session:
            tenant = session.scalar(select(Tenant).where(Tenant.slug == "default"))
            assert tenant is not None
            run_id = str(uuid.uuid4())
            job_id = new_rq_job_id(run_id)
            payload = {
                "topic": "Live service integration smoke test",
                "question": "Can a real PostgreSQL and Redis/RQ stack complete an offline traceable research run?",
                "source_limit": 2,
                "demo_mode": True,
            }
            session.add(ResearchJob(
                id=run_id,
                tenant_id=tenant.id,
                status="queued",
                request_json=payload,
                attempts=0,
                rq_job_id=job_id,
            ))
            session.commit()

        assert enqueue_research_run(run_id, payload, job_id=job_id) == job_id
        connection = Redis.from_url(redis_url)
        queue = Queue("argumentum", connection=connection)
        worker = SimpleWorker([queue], connection=connection)
        worker.work(burst=True, with_scheduler=False)

        rq_job = Job.fetch(job_id, connection=connection)
        assert rq_job.get_status(refresh=True).value == "finished"
        with factory() as session:
            persisted = session.get(ResearchJob, run_id)
            assert persisted is not None
            assert persisted.status in {"completed", "completed_with_warnings"}
            assert persisted.tenant_id == tenant.id
        assert (data_dir / "runs" / run_id / "RUN_SUMMARY.md").is_file()
        assert (data_dir / "runs" / run_id / "run_manifest.json").is_file()
        connection.close()
    finally:
        redis.flushdb()
        redis.close()
        get_engine().dispose()
        get_engine.cache_clear()
