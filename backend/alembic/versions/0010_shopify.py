"""Shopify: per-business settings (store credential, order lookup, notifications).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db_types import EMPTY_JSON, JSON_DOC

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("shopify_settings", JSON_DOC, nullable=False, server_default=EMPTY_JSON),
    )


def downgrade() -> None:
    op.drop_column("tenants", "shopify_settings")
