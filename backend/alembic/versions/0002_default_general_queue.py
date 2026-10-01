"""Give every existing tenant without queues a catch-all "General" queue.

New tenants get this queue automatically (app/services/tenants.py). This data
migration does the same for tenants created before queue matching existed, so
their new cases don't end up unrouted.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-28
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Snapshot of the defaults at the time of writing. Migrations must not import app
# code: if the app changes later, this migration must still do exactly what it did.
GENERAL_DESCRIPTION = (
    "Catch-all: receives every case no other queue matches. Keep it last (highest priority number)."
)
DEFAULT_SETTINGS = {
    "gen_ai_allowed": False,
    "auto_send": False,
    "approval_threshold": None,
    "sla_first_response_hours": None,
    "reopen_window_hours": 72,
}

queues = sa.table(
    "queues",
    sa.column("id", sa.Uuid()),
    sa.column("tenant_id", sa.Uuid()),
    sa.column("name", sa.String()),
    sa.column("description", sa.Text()),
    sa.column("priority", sa.Integer()),
    sa.column("is_active", sa.Boolean()),
    sa.column("match_criteria", postgresql.JSONB()),
    sa.column("settings", postgresql.JSONB()),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)


def upgrade() -> None:
    connection = op.get_bind()
    tenant_ids = (
        connection.execute(
            sa.text(
                "SELECT id FROM tenants WHERE NOT EXISTS "
                "(SELECT 1 FROM queues WHERE queues.tenant_id = tenants.id)"
            )
        )
        .scalars()
        .all()
    )
    now = datetime.now(UTC)
    rows = [
        {
            "id": uuid.uuid4(),
            "tenant_id": tenant_id,
            "name": "General",
            "description": GENERAL_DESCRIPTION,
            "priority": 1000,
            "is_active": True,
            "match_criteria": {"match": "all", "conditions": []},
            "settings": DEFAULT_SETTINGS,
            "created_at": now,
            "updated_at": now,
        }
        for tenant_id in tenant_ids
    ]
    if rows:
        op.bulk_insert(queues, rows)
    print(f"Added a General queue to {len(rows)} tenant(s).")  # noqa: T201 - migration log


def downgrade() -> None:
    # Data-only migration: nothing to undo structurally. Removing the queues could
    # orphan cases routed to them since, so downgrade intentionally leaves them.
    pass
