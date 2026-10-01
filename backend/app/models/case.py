import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.domain.lifecycle import CaseStatus
from app.models.base import Base, CreatedAtMixin, IdMixin, JSONType, utcnow
from app.models.customer import Customer
from app.models.queue import Queue


class Case(IdMixin, CreatedAtMixin, Base):
    """The case: the *current state* of one customer issue.

    Mirrors docs/case.v2.example.json. The full history lives elsewhere:
    messages in `messages`, every status change in `case_events`.

    Strict columns are used for anything we filter, sort or join on (status,
    queue, assignee, timestamps). Flexible JSON is used for sections whose
    shape varies by tenant or by connector (attributes, enrichment, ...).

    `version` enables **optimistic locking**: SQLAlchemy adds
    `WHERE version = <what we loaded>` to every UPDATE. If someone else (an
    agent, the AI, the worker) saved the case in between, the update matches
    no rows and raises instead of silently overwriting their change.
    """

    __tablename__ = "cases"
    __table_args__ = (
        Index("ix_cases_tenant_status_queue", "tenant_id", "status", "queue_id"),
        Index("ix_cases_tenant_customer_created", "tenant_id", "customer_id", "created_at"),
    )

    # Public case ID: creation time as a Unix timestamp in microseconds (app/domain/ids.py).
    # Shown to people and used in URLs/API paths. `id` (UUID) stays internal.
    case_number: Mapped[int] = mapped_column(BigInteger, unique=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    customer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("customers.id"))
    # Loaded together with the case (one JOIN) so the API can show name/email.
    customer: Mapped[Customer] = relationship(lazy="joined")

    # Lifecycle — values come from app.domain.lifecycle.CaseStatus.
    status: Mapped[str] = mapped_column(String(32), default=CaseStatus.INTAKE.value)
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    channel: Mapped[str] = mapped_column(String(32))  # webform | email | chat | api
    language: Mapped[str] = mapped_column(String(16), default="en")

    # {"customerSelected": {...}, "effective": {...}, "source": "customer" | "ai" | "agent"}
    category: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # tenant fields
    flags: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # sensitive, regulated
    sla: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    enrichment: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    decisions: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    # Assignment — who/where the case currently is. History is in case_events.
    queue_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("queues.id", ondelete="SET NULL"))
    queue: Mapped[Queue | None] = relationship(lazy="joined")
    assignee_type: Mapped[str | None] = mapped_column(String(16))  # human | ai
    assignee_id: Mapped[str | None] = mapped_column(String(100))
    assignment_pinned: Mapped[bool] = mapped_column(Boolean, default=False)

    version: Mapped[int] = mapped_column(Integer)

    __mapper_args__ = {"version_id_col": version}
