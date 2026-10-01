import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, JSONListType, JSONType, utcnow


class PromptTemplate(IdMixin, CreatedAtMixin, Base):
    """A business's Jinja prompt template, identified by its file-style name.

    Names decide what a template is for (app/ai/templates/README.md):
      base.jinja                         tone & empathy baseline for every reply
      queue/<Queue>.jinja                persona for a queue (queue/_default.jinja = fallback)
      category/<Type>_<Category>_<Sub>.jinja   how to answer a kind of case

    The content lives in versions; `current_version` is used for new drafts.
    """

    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_prompt_templates_tenant_name"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))  # base | persona | category
    description: Mapped[str | None] = mapped_column(Text)
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class PromptTemplateVersion(IdMixin, CreatedAtMixin, Base):
    """One saved version of a template. Never changed after it's written.

    Drafts record the name and version of each template layer they used, so
    any reply can be traced back to the exact prompt text.
    """

    __tablename__ = "prompt_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "template_id", "version", name="uq_prompt_template_versions_template_version"
        ),
    )

    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(Text)  # Jinja, without the header
    # Automated checks (app/ai/checks.py); combined across layers when drafting.
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
    """A batch of test drafts: one template (as saved or as edited) × models × inputs × runs.

    The other layers resolve normally for each input. Executed by the worker
    (job kind "template_test"); `results` fills in as each draft completes.
    """

    __tablename__ = "template_test_runs"
    __table_args__ = (Index("ix_template_test_runs_tenant_created", "tenant_id", "created_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    template_name: Mapped[str | None] = mapped_column(String(200))
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
