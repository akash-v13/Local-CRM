"""Business profile: where the business sells (setup checklist, recommended integrations).

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db_types import EMPTY_JSON, JSON_DOC

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants",
        sa.Column("profile", JSON_DOC, nullable=False, server_default=EMPTY_JSON),
    )


def downgrade() -> None:
    op.drop_column("tenants", "profile")
