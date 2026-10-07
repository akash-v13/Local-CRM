import uuid
from typing import Any

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, JSONType


class Message(IdMixin, CreatedAtMixin, Base):
    """One piece of correspondence on a case (customer email, agent reply, AI draft, note).

    Stored in its own table rather than inside the case, so case rows stay
    small no matter how long a thread gets.
    """

    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_case_created", "case_id", "created_at"),
        # Email Message-ID: finds the case a reply belongs to, and stops an email
        # being imported twice. NULL for non-email messages (NULLs don't clash).
        Index("uq_messages_tenant_external_id", "tenant_id", "external_id", unique=True),
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))

    direction: Mapped[str] = mapped_column(String(16))  # inbound | outbound | internal
    channel: Mapped[str] = mapped_column(String(32))  # webform | email | chat | note
    author_type: Mapped[str] = mapped_column(String(16))  # customer | human | ai | system
    author_id: Mapped[str | None] = mapped_column(String(100))
    visibility: Mapped[str] = mapped_column(String(16))  # public | draft | internal
    body: Mapped[str] = mapped_column(Text)
    # For AI-written messages: model, prompt version, token counts.
    ai: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    # Email messages: the RFC 5322 Message-ID ("<…@…>").
    external_id: Mapped[str | None] = mapped_column(String(998))
    # Email messages: subject, from, to, threading headers, attachments (names and
    # sizes only) and, for outbound mail, delivery status. See app/email/.
    email: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
