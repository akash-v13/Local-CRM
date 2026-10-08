"""Reading messages: business settings for what to pull out, and the result on each case.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db_types import EMPTY_JSON, JSON_DOC

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("reading_settings", JSON_DOC, nullable=False, server_default=EMPTY_JSON),
    )
    op.add_column(
        "cases", sa.Column("extraction", JSON_DOC, nullable=False, server_default=EMPTY_JSON)
    )


def downgrade() -> None:
    op.drop_column("cases", "extraction")
    op.drop_column("tenants", "reading_settings")
