"""Add cases.case_number: the public case ID (Unix timestamp in microseconds).

Existing cases are backfilled from their own `created_at`, so their numbers
reflect when they were really created. If two existing cases share the same
microsecond, the later one gets the next free number, so all numbers are unique.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-30
"""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def upgrade() -> None:
    # 1. Add as nullable so existing rows are allowed while we fill them in.
    op.add_column("cases", sa.Column("case_number", sa.BigInteger(), nullable=True))

    # 2. Backfill in creation order, guaranteeing unique, increasing numbers:
    #    number = max(created_at in microseconds, previous number + 1).
    #    Exact integer arithmetic (no floating point), done in one ordered pass.
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT id, created_at FROM cases ORDER BY created_at, id"))
    updates = []
    previous = 0
    for case_id, created_at in rows:
        if isinstance(created_at, str):  # SQLite returns raw text from a plain SELECT
            created_at = datetime.fromisoformat(created_at)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        micros = (created_at - EPOCH) // timedelta(microseconds=1)
        previous = max(micros, previous + 1)
        updates.append({"id": case_id, "n": previous})
    if updates:
        connection.execute(sa.text("UPDATE cases SET case_number = :n WHERE id = :id"), updates)

    # 3. Now every row has one: require it and enforce uniqueness. (Batch mode: SQLite
    #    can't alter columns or add constraints in place, so it rebuilds the table.)
    with op.batch_alter_table("cases") as batch:
        batch.alter_column("case_number", existing_type=sa.BigInteger(), nullable=False)
        batch.create_unique_constraint(op.f("uq_cases_case_number"), ["case_number"])


def downgrade() -> None:
    with op.batch_alter_table("cases") as batch:
        batch.drop_constraint(op.f("uq_cases_case_number"), type_="unique")
        batch.drop_column("case_number")
