"""AI reply drafting: reply templates (+ immutable versions), sample cases, test runs.

Also gives every existing tenant a catch-all "Default reply" template (new
tenants get it from TenantService.create).

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONB = postgresql.JSONB(astext_type=sa.Text())

# Snapshot of the default template at the time of writing (migrations must not import app code).
DEFAULT_INSTRUCTIONS = (
    "Write a short, warm, professional reply. Acknowledge the customer's concern in your own "
    "words, explain what the facts show and what happens next, and close politely. "
    "Keep it to 2-4 short paragraphs."
)


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "reply_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("match_criteria", JSONB, nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_reply_templates_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reply_templates")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_reply_templates_tenant_name"),
    )
    op.create_index(
        "ix_reply_templates_tenant_active_priority",
        "reply_templates",
        ["tenant_id", "is_active", "priority"],
    )

    op.create_table(
        "reply_template_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(length=40), nullable=False),
        sa.Column("effort", sa.String(length=8), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("rules", JSONB, nullable=False),
        sa.Column("example_reply", sa.Text(), nullable=True),
        sa.Column("max_words", sa.Integer(), nullable=True),
        sa.Column("must_include", JSONB, nullable=False),
        sa.Column("must_not_include", JSONB, nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["reply_templates.id"],
            name=op.f("fk_reply_template_versions_template_id_reply_templates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reply_template_versions")),
        sa.UniqueConstraint(
            "template_id", "version", name="uq_reply_template_versions_template_version"
        ),
    )

    op.create_table(
        "sample_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("category", JSONB, nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=True),
        sa.Column("customer_tier", sa.String(length=50), nullable=True),
        sa.Column("queue_name", sa.String(length=200), nullable=True),
        sa.Column("facts", JSONB, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_sample_cases_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sample_cases")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_sample_cases_tenant_name"),
    )

    op.create_table(
        "template_test_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=True),
        sa.Column("template_version", sa.Integer(), nullable=True),
        sa.Column("config", JSONB, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("total_calls", sa.Integer(), nullable=False),
        sa.Column("results", JSONB, nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column("actual_cost_usd", sa.Float(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["reply_templates.id"],
            name=op.f("fk_template_test_runs_template_id_reply_templates"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_template_test_runs_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_template_test_runs")),
    )
    op.create_index(
        "ix_template_test_runs_tenant_created", "template_test_runs", ["tenant_id", "created_at"]
    )

    # Backfill: a default template for every existing tenant.
    connection = op.get_bind()
    tenant_ids = connection.execute(sa.text("SELECT id FROM tenants")).scalars().all()
    now = datetime.now(UTC)
    templates = sa.table(
        "reply_templates",
        *[
            sa.column(n)
            for n in (
                "id",
                "tenant_id",
                "name",
                "description",
                "priority",
                "is_active",
                "current_version",
                "created_at",
                "updated_at",
            )
        ],
        sa.column("match_criteria", JSONB),
    )
    versions = sa.table(
        "reply_template_versions",
        *[
            sa.column(n)
            for n in (
                "id",
                "template_id",
                "version",
                "model",
                "effort",
                "instructions",
                "example_reply",
                "max_words",
                "created_by",
                "created_at",
            )
        ],
        sa.column("rules", JSONB),
        sa.column("must_include", JSONB),
        sa.column("must_not_include", JSONB),
    )
    template_rows, version_rows = [], []
    for tenant_id in tenant_ids:
        template_id = uuid.uuid4()
        template_rows.append(
            {
                "id": template_id,
                "tenant_id": tenant_id,
                "name": "Default reply",
                "description": "Used when no other template matches.",
                "priority": 1000,
                "is_active": True,
                "current_version": 1,
                "created_at": now,
                "updated_at": now,
                "match_criteria": {"match": "all", "conditions": []},
            }
        )
        version_rows.append(
            {
                "id": uuid.uuid4(),
                "template_id": template_id,
                "version": 1,
                "model": "claude-sonnet-5",
                "effort": "low",
                "instructions": DEFAULT_INSTRUCTIONS,
                "example_reply": None,
                "max_words": 180,
                "created_by": "system",
                "created_at": now,
                "rules": [],
                "must_include": [],
                "must_not_include": [],
            }
        )
    if template_rows:
        op.bulk_insert(templates, template_rows)
        op.bulk_insert(versions, version_rows)


def downgrade() -> None:
    op.drop_table("template_test_runs")
    op.drop_table("sample_cases")
    op.drop_table("reply_template_versions")
    op.drop_table("reply_templates")
