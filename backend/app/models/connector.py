import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, JSONListType, JSONType, utcnow


class Connector(IdMixin, CreatedAtMixin, Base):
    """An external API call that enriches cases with data (Idea 2).

    Example: GET https://shop.example.com/orders/{{case.attributes.orderNumber}}
    with an API key, keeping `total.amount` as `orderTotal` and `carrier` as
    `carrier`. Results land on the case under enrichment.<key>.<field>.

    - `run_order`: connectors run one after another, lowest first, so a later
      connector can use an earlier one's fields in its templates.
    - `run_when`: optional criteria (same format as queue match criteria); the
      connector is skipped for cases that don't match. Empty = always run.
    - `required`: if a required connector fails, the case goes to
      EnrichmentFailed instead of being routed with partial data.
    - `credential_id`: how to authenticate (app/models/credential.py), shared
      with other connectors for the same API. None = no authentication.
    """

    __tablename__ = "connectors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "key", name="uq_connectors_tenant_key"),
        Index("ix_connectors_tenant_active_order", "tenant_id", "is_active", "run_order"),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(40))  # e.g. "shop"; used in enrichment.<key>.<field>
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    run_order: Mapped[int] = mapped_column(Integer, default=100)
    required: Mapped[bool] = mapped_column(Boolean, default=False)

    method: Mapped[str] = mapped_column(String(8))  # GET | POST
    url_template: Mapped[str] = mapped_column(Text)
    headers: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # non-secret headers
    body_template: Mapped[str | None] = mapped_column(Text)  # JSON with {{placeholders}}, POST only

    credential_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("credentials.id"))

    timeout_seconds: Mapped[float] = mapped_column(Float, default=5.0)
    max_retries: Mapped[int] = mapped_column(Integer, default=1)

    run_when: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # [{"path": "total.amount", "target": "orderTotal", "label": "Order total"}, ...]
    field_mappings: Mapped[list[Any]] = mapped_column(JSONListType, default=list)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
