import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, JSONType, utcnow


class CaseEvent(IdMixin, Base):
    """Append-only history of everything that happened to a case.

    Rows are only ever inserted, never updated or deleted. This table is the
    audit trail, and later the source for SLA tracking and time-in-status
    analytics.
    """

    __tablename__ = "case_events"
    __table_args__ = (Index("ix_case_events_case_occurred", "case_id", "occurred_at"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))

    event_type: Mapped[str] = mapped_column(String(64))  # e.g. case.created, case.status_changed
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str | None] = mapped_column(String(32))
    actor_type: Mapped[str] = mapped_column(String(16))  # customer | human | ai | system
    actor_id: Mapped[str | None] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
