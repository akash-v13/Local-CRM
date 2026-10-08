"""Email channel: linked inboxes (IMAP/SMTP), email details on messages, inbox on cases.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db_types import EMPTY_JSON, JSON_DOC

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mailboxes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("imap_host", sa.String(length=255), nullable=False),
        sa.Column("imap_port", sa.Integer(), nullable=False),
        sa.Column("imap_security", sa.String(length=16), nullable=False),
        sa.Column("smtp_host", sa.String(length=255), nullable=False),
        sa.Column("smtp_port", sa.Integer(), nullable=False),
        sa.Column("smtp_security", sa.String(length=16), nullable=False),
        sa.Column("username", sa.String(length=320), nullable=False),
        sa.Column("password_encrypted", sa.Text(), nullable=False),
        sa.Column("folder", sa.String(length=200), nullable=False),
        sa.Column("import_since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mark_as_read", sa.Boolean(), nullable=False),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("default_category", JSON_DOC, nullable=True),
        sa.Column("uid_validity", sa.BigInteger(), nullable=True),
        sa.Column("last_uid", sa.BigInteger(), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("imported_total", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "address", name="uq_mailboxes_tenant_address"),
    )
    op.add_column("messages", sa.Column("external_id", sa.String(length=998), nullable=True))
    op.add_column(
        "messages",
        sa.Column("email", JSON_DOC, nullable=False, server_default=EMPTY_JSON),
    )
    op.create_index(
        "uq_messages_tenant_external_id", "messages", ["tenant_id", "external_id"], unique=True
    )
    # Batch mode: SQLite can't add a foreign key in place, so it rebuilds the table.
    with op.batch_alter_table("cases") as batch:
        batch.add_column(sa.Column("mailbox_id", sa.Uuid(), nullable=True))
        batch.create_foreign_key(
            "fk_cases_mailbox_id", "mailboxes", ["mailbox_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("cases") as batch:
        batch.drop_constraint("fk_cases_mailbox_id", type_="foreignkey")
        batch.drop_column("mailbox_id")
    op.drop_index("uq_messages_tenant_external_id", table_name="messages")
    op.drop_column("messages", "email")
    op.drop_column("messages", "external_id")
    op.drop_table("mailboxes")
