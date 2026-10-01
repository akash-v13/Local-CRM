import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, JSONListType, JSONType, utcnow


class ReplyTemplate(IdMixin, CreatedAtMixin, Base):
    """How AI drafts replies for a kind of case.

    Chosen like queues: active templates are checked by `priority` (lower
    first) and the first whose `match_criteria` match the case is used. The
    wording itself lives in versions (ReplyTemplateVersion); `current_version`
    is the one used for new drafts.
    """

    __tablename__ = "reply_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_reply_templates_tenant_name"),
        Index("ix_reply_templates_tenant_active_priority", "tenant_id", "is_active", "priority"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    match_criteria: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ReplyTemplateVersion(IdMixin, CreatedAtMixin, Base):
    """One saved version of a template's content. Never changed after it's written.

    Every draft records the template id and version that produced it, so you
    can always trace a reply back to the exact instructions used.
    """

    __tablename__ = "reply_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "template_id", "version", name="uq_reply_template_versions_template_version"
        ),
    )

    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("reply_templates.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(40))
    effort: Mapped[str] = mapped_column(String(8))
    instructions: Mapped[str] = mapped_column(Text)
    rules: Mapped[list[Any]] = mapped_column(JSONListType, default=list)
    example_reply: Mapped[str | None] = mapped_column(Text)
    # Automated checks (app/ai/checks.py)
    max_words: Mapped[int | None] = mapped_column(Integer)
    must_include: Mapped[list[Any]] = mapped_column(JSONListType, default=list)
    must_not_include: Mapped[list[Any]] = mapped_column(JSONListType, default=list)
    created_by: Mapped[str | None] = mapped_column(String(100))


class SampleCase(IdMixin, CreatedAtMixin, Base):
    """A reusable test input for the template test lab: a customer message plus facts."""

    __tablename__ = "sample_cases"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_sample_cases_tenant_name"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    channel: Mapped[str] = mapped_column(String(32), default="webform")
    category: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    customer_name: Mapped[str | None] = mapped_column(String(200))
    customer_tier: Mapped[str | None] = mapped_column(String(50))
    queue_name: Mapped[str | None] = mapped_column(String(200))
    facts: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # e.g. daysLate: 6
    message: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class TemplateTestRun(IdMixin, CreatedAtMixin, Base):
    """A batch of test drafts: template (as saved or as edited) × models × inputs × runs.

    Executed by the worker (job kind "template_test"); `results` fills in as
    each draft completes, so the UI can show progress.
    """

    __tablename__ = "template_test_runs"
    __table_args__ = (Index("ix_template_test_runs_tenant_created", "tenant_id", "created_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reply_templates.id", ondelete="SET NULL")
    )
    template_version: Mapped[int | None] = mapped_column(Integer)  # None = unsaved edits
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    total_calls: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[list[Any]] = mapped_column(JSONListType, default=list)
    estimated_cost_usd: Mapped[float] = mapped_column(default=0.0)
    actual_cost_usd: Mapped[float] = mapped_column(default=0.0)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
