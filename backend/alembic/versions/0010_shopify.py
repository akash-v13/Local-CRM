"""Shopify: per-business settings (store credential, order lookup, notifications).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("shopify_settings", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("tenants", "shopify_settings")
