"""Reading messages: business settings for what to pull out, and the result on each case.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())
EMPTY = sa.text("'{}'::jsonb")


def upgrade() -> None:
    op.add_column(
        "tenants", sa.Column("reading_settings", JSONB, nullable=False, server_default=EMPTY)
    )
    op.add_column("cases", sa.Column("extraction", JSONB, nullable=False, server_default=EMPTY))


def downgrade() -> None:
    op.drop_column("cases", "extraction")
    op.drop_column("tenants", "reading_settings")
