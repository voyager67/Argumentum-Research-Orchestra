"""Create initial research job table."""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial_jobs"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("output_path", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("rq_job_id", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_research_jobs_status", "research_jobs", ["status"])


def downgrade() -> None:
    op.drop_index("ix_research_jobs_status", table_name="research_jobs")
    op.drop_table("research_jobs")
