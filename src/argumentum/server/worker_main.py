"""Start RQ with the scheduler enabled so delayed retries are actually dispatched."""

from __future__ import annotations

import os


def main() -> None:
    try:
        from redis import Redis
        from rq import Queue, Worker
    except ImportError as exc:  # pragma: no cover - exercised in minimal installations
        raise RuntimeError("Self-hosted queue dependencies are missing. Install argumentum[server].") from exc

    connection = Redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        socket_connect_timeout=5,
        socket_timeout=5,
        health_check_interval=30,
    )
    connection.ping()
    queue = Queue("argumentum", connection=connection)
    worker = Worker([queue], connection=connection)
    worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
