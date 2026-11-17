"""Periodic reconciler for durable PostgreSQL jobs and Redis Queue publications."""

from __future__ import annotations

import logging
import os
import time

from .recovery import reconcile_jobs

LOGGER = logging.getLogger("argumentum.reconciler")


def main() -> None:
    """Run reconciliation continuously; API maintenance route remains available too."""
    interval = max(15, min(int(os.getenv("ARGUMENTUM_RECONCILE_INTERVAL_SECONDS", "60")), 3600))
    stale_after = max(60, min(int(os.getenv("ARGUMENTUM_STALE_WORKER_SECONDS", "1800")), 86_400))
    batch_size = max(1, min(int(os.getenv("ARGUMENTUM_RECONCILE_BATCH_SIZE", "50")), 200))
    LOGGER.info(
        "Reconciler started (interval_seconds=%s, stale_worker_seconds=%s, batch_size=%s)",
        interval,
        stale_after,
        batch_size,
    )
    while True:
        try:
            report = reconcile_jobs(limit=batch_size, stale_after_seconds=stale_after)
            LOGGER.info(
                "Reconciliation complete (examined=%s, requeued=%s, active=%s, skipped=%s, failed=%s)",
                report.get("examined", 0),
                len(report.get("requeued", [])),
                len(report.get("active", [])),
                len(report.get("skipped", [])),
                len(report.get("failed", [])),
            )
        except Exception as exc:
            # Do not persist or log exception messages; they may contain connection details.
            LOGGER.error("Reconciliation cycle failed (%s)", type(exc).__name__)
        time.sleep(interval)


if __name__ == "__main__":
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    main()
