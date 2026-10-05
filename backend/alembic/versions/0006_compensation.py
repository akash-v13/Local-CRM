"""Compensation matrix: rules per tenant, tenant-wide guardrail settings.

Decisions are stored on the case (`cases.decisions["compensation"]`), which
already exists, so cases need no schema change.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.create_table(
        "compensation_rules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("match_criteria", JSONB, nullable=False),
        sa.Column("outcome", JSONB, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_compensation_rules_tenant_active_priority",
        "compensation_rules",
        ["tenant_id", "is_active", "priority"],
    )
    op.add_column(
        "tenants",
        sa.Column(
            "compensation_settings", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
    )


def downgrade() -> None:
    op.drop_column("tenants", "compensation_settings")
    op.drop_index("ix_compensation_rules_tenant_active_priority", table_name="compensation_rules")
    op.drop_table("compensation_rules")
