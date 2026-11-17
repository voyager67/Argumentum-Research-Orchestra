"""Add tenant-scoped research projects and project-run association.

Revision ID: 0004_research_projects
Revises: 0003_tenants_and_credentials
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_research_projects"
down_revision = "0003_tenants_and_credentials"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_projects",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_research_projects_tenant_slug"),
    )
    op.create_index("ix_research_projects_tenant_id", "research_projects", ["tenant_id"])
    op.create_index("ix_research_projects_status", "research_projects", ["status"])
    with op.batch_alter_table("research_jobs") as batch_op:
        batch_op.add_column(sa.Column("project_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_research_jobs_project_id_research_projects", "research_projects", ["project_id"], ["id"], ondelete="SET NULL"
        )
    op.create_index("ix_research_jobs_project_id", "research_jobs", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_research_jobs_project_id", table_name="research_jobs")
    with op.batch_alter_table("research_jobs") as batch_op:
        batch_op.drop_constraint("fk_research_jobs_project_id_research_projects", type_="foreignkey")
        batch_op.drop_column("project_id")
    op.drop_index("ix_research_projects_status", table_name="research_projects")
    op.drop_index("ix_research_projects_tenant_id", table_name="research_projects")
    op.drop_table("research_projects")
