import uuid
from typing import Any

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, JSONType


class Customer(IdMixin, CreatedAtMixin, Base):
    """An end customer of a tenant (the person who opens cases).

    `identity_links` will hold other emails / phones / payout accounts known to
    belong to the same person — the basis for repeat-claim and fraud checks.
    """

    __tablename__ = "customers"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_customers_tenant_email"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    email: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(200))
    tier: Mapped[str | None] = mapped_column(String(50))
    identity_links: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
