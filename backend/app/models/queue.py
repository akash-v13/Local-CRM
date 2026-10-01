import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, JSONType, utcnow


class Queue(IdMixin, CreatedAtMixin, Base):
    """A queue is a *policy bundle* (Idea 7): where cases go and how they're handled.

    - `priority`: lower number = checked first during queue matching.
    - `match_criteria`: the routing rule, e.g.
      `{"all": [{"field": "category.effective.category", "equals": "Delivery"},
                {"keyword": "late"}]}`
    - `settings`: handling policy, e.g.
      `{"genAiAllowed": true, "autoSend": false, "approvalThreshold": 25,
        "slaPolicyId": "...", "reopenWindowHours": 72}`

    Not yet implemented: publishing immutable versions (see docs/05-data-model.md §5.4).
    """

    __tablename__ = "queues"
    __table_args__ = (
        Index("ix_queues_tenant_active_priority", "tenant_id", "is_active", "priority"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    match_criteria: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
