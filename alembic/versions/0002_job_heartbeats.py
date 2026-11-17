"""Add worker lease heartbeat for safe stale-job recovery."""

import sqlalchemy as sa
from alembic import op

revision = "0002_job_heartbeats"
down_revision = "0001_initial_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("research_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_research_jobs_heartbeat_at", "research_jobs", ["heartbeat_at"])


def downgrade() -> None:
    op.drop_index("ix_research_jobs_heartbeat_at", table_name="research_jobs")
    op.drop_column("research_jobs", "heartbeat_at")
