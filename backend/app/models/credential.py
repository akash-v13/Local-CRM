import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, JSONType, utcnow


class Credential(IdMixin, CreatedAtMixin, Base):
    """How to authenticate to an external API. Shared by every connector that uses it.

    kind:
      api_key                    secrets: key                   config: header_name
      bearer                     secrets: token
      basic                      secrets: username, password
      oauth2_client_credentials  secrets: client_id, client_secret  config: token_url, scope…
      token_request              secrets: any named values      config: url, body, token_path…

    For the two token kinds, the generated access token is cached here,
    encrypted, with its expiry, so all connectors and workers share one token
    and only refresh it when it's about to expire (app/connectors/auth.py).

    Everything secret (`secrets_ciphertext`, `token_ciphertext`) is encrypted
    and never returned by the API.
    """

    __tablename__ = "credentials"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_credentials_tenant_name"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(32))
    config: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)  # non-secret settings
    secrets_ciphertext: Mapped[str | None] = mapped_column(Text)  # encrypted JSON object

    token_ciphertext: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    token_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
