from typing import Any

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, JSONType


class Tenant(IdMixin, CreatedAtMixin, Base):
    """A business using the platform. Every other table carries a `tenant_id`."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200))
    # Compensation guardrails (repeat-claimant check, default currency); see
    # app/domain/compensation.py `Settings`. Empty = defaults.
    compensation_settings: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # Reading incoming messages (fields to pull out, category); see app/services/reading.py.
    reading_settings: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # Issuing compensation (Stripe credential, methods, payment lookup); services/payouts.py.
    payout_settings: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # The business's Shopify store (credential, order lookup); services/shopify.py.
    shopify_settings: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
