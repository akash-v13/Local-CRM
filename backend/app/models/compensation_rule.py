import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, JSONType, utcnow


class CompensationRule(IdMixin, CreatedAtMixin, Base):
    """One row of a business's compensation matrix (see app/domain/compensation.py).

    - `priority`: lower number = checked first; the first matching rule decides.
    - `match_criteria`: same shape as a queue's (fields, operators, all/any).
    - `outcome`: what the customer gets, e.g.
      `{"type": "refund", "amount_mode": "percent", "percent": 50,
        "percent_of": "enrichment.shop_orders.orderTotal", "cap": 100,
        "currency": "USD", "requires_approval": false}`

    Rules are deactivated, never deleted: decisions on cases refer to them.
    """

    __tablename__ = "compensation_rules"
    __table_args__ = (
        Index("ix_compensation_rules_tenant_active_priority", "tenant_id", "is_active", "priority"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    match_criteria: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    outcome: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
