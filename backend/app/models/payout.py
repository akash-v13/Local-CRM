import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, JSONType, utcnow


class Payout(IdMixin, CreatedAtMixin, Base):
    """Compensation actually issued (or being issued) to a customer, e.g. a Stripe refund.

    One row per approved compensation decision: `idempotency_key` is derived from
    the case and the decision and is unique, so a decision can never be paid twice.
    The same key is sent to the provider (Stripe's Idempotency-Key), which protects
    retries of an in-flight request.

    status: queued → processing → succeeded | failed  (retrying between attempts)
    """

    __tablename__ = "payouts"
    __table_args__ = (
        Index("uq_payouts_idempotency_key", "idempotency_key", unique=True),
        Index("ix_payouts_tenant_created", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(32))  # refund | store_credit | voucher
    provider: Mapped[str] = mapped_column(String(32))  # stripe
    method: Mapped[str] = mapped_column(
        String(32)
    )  # stripe_refund | stripe_credit | stripe_voucher
    amount: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(16), default="queued")
    idempotency_key: Mapped[str] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(255))  # re_…, cbtxn_…, promo_…
    # Provider details: payment intent / customer used, voucher code, provider status.
    details: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_by: Mapped[str | None] = mapped_column(String(100))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
