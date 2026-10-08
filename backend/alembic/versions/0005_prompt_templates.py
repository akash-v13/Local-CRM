"""AI reply drafting: Jinja prompt templates (+ immutable versions), sample cases, test runs.

Existing tenants get the starter templates the first time they're needed
(PromptTemplateService.ensure_defaults), not here: a migration must not depend
on template files that keep evolving.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.db_types import JSON_DOC

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_prompt_templates_tenant_id_tenants"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_templates")),
        sa.UniqueConstraint("tenant_id", "name", name="uq_prompt_templates_tenant_name"),
    )
    op.create_table(
        "prompt_template_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("max_words", sa.Integer(), nullable=True),
        sa.Column("must_include", JSON_DOC, nullable=False),
        sa.Column("must_not_include", JSON_DOC, nullable=False),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["prompt_templates.id"],
            name=op.f("fk_prompt_template_versions_template_id_prompt_templates"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_prompt_template_versions")),
        sa.UniqueConstraint(
            "template_id", "version", name="uq_prompt_template_versions_template_version"
        ),
    )
    op.create_table(
        "sample_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("channel", sa.String(length=32), nullable=False),
        sa.Column("category", JSON_DOC, nullable=False),
        sa.Column("customer_name", sa.String(length=200), nullable=True),
        sa.Column("customer_tier", sa.String(length=50), nullable=True),
        sa.Column("queue_name", sa.String(length=200), nullable=True),
        sa.Column("facts", JSON_DOC, nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.Column("template_name", sa.String(length=200), nullable=True),
        sa.Column("config", JSON_DOC, nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("total_calls", sa.Integer(), nullable=False),
        sa.Column("results", JSON_DOC, nullable=False),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False),
        sa.Column("actual_cost_usd", sa.Float(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
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


def downgrade() -> None:
    op.drop_table("template_test_runs")
    op.drop_table("sample_cases")
    op.drop_table("prompt_template_versions")
    op.drop_table("prompt_templates")
