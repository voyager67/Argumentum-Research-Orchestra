"""Add tenant-scoped API credentials and research-job ownership.

Revision ID: 0003_tenants_and_credentials
Revises: 0002_job_heartbeats
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_tenants_and_credentials"
down_revision = "0002_job_heartbeats"
branch_labels = None
depends_on = None

DEFAULT_TENANT_ID = "00000000-0000-4000-8000-000000000001"


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)
    op.create_table(
        "api_credentials",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_bootstrap", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_credentials_tenant_id", "api_credentials", ["tenant_id"])
    op.create_index("ix_api_credentials_token_hash", "api_credentials", ["token_hash"], unique=True)

    # Existing service installations have jobs but no tenant model. Preserve all
    # records by assigning them to a dedicated default workspace before enforcing
    # NOT NULL ownership on the research_jobs table.
    op.execute(
        sa.text(
            "INSERT INTO tenants (id, name, slug, is_active, created_at) "
            "VALUES (:id, 'Default workspace', 'default', TRUE, CURRENT_TIMESTAMP)"
        ).bindparams(id=DEFAULT_TENANT_ID)
    )
    with op.batch_alter_table("research_jobs") as batch_op:
        batch_op.add_column(sa.Column("tenant_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_research_jobs_tenant_id_tenants", "tenants", ["tenant_id"], ["id"], ondelete="RESTRICT"
        )
    op.execute(
        sa.text("UPDATE research_jobs SET tenant_id = :tenant_id WHERE tenant_id IS NULL").bindparams(
            tenant_id=DEFAULT_TENANT_ID
        )
    )
    with op.batch_alter_table("research_jobs") as batch_op:
        batch_op.alter_column("tenant_id", existing_type=sa.String(length=36), nullable=False)
    op.create_index("ix_research_jobs_tenant_id", "research_jobs", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_research_jobs_tenant_id", table_name="research_jobs")
    with op.batch_alter_table("research_jobs") as batch_op:
        batch_op.drop_constraint("fk_research_jobs_tenant_id_tenants", type_="foreignkey")
        batch_op.drop_column("tenant_id")
    op.drop_index("ix_api_credentials_token_hash", table_name="api_credentials")
    op.drop_index("ix_api_credentials_tenant_id", table_name="api_credentials")
    op.drop_table("api_credentials")
    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
