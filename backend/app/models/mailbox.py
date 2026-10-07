import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, JSONType, utcnow


class Mailbox(IdMixin, CreatedAtMixin, Base):
    """A business's support inbox, linked over IMAP (read) and SMTP (send).

    The worker polls it: every new email becomes a case, or a reply on an
    existing case when it belongs to that conversation. Agent replies on
    cases from this inbox are sent from it. See app/services/email.py.

    - `password_encrypted`: the (app) password, encrypted like connector secrets;
      never returned by the API.
    - `import_since`: emails older than this are ignored (link time minus any backfill).
    - `uid_validity` / `last_uid`: where the last poll stopped (IMAP UIDs), so each
      poll only fetches new messages. A changed UIDVALIDITY means the server
      renumbered the folder: polling restarts from `import_since`, and duplicates
      are prevented by the Message-ID check.
    """

    __tablename__ = "mailboxes"
    __table_args__ = (UniqueConstraint("tenant_id", "address", name="uq_mailboxes_tenant_address"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    address: Mapped[str] = mapped_column(String(320))
    display_name: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    provider: Mapped[str] = mapped_column(String(32), default="custom")

    imap_host: Mapped[str] = mapped_column(String(255))
    imap_port: Mapped[int] = mapped_column(Integer)
    imap_security: Mapped[str] = mapped_column(String(16))  # ssl | starttls | none
    smtp_host: Mapped[str] = mapped_column(String(255))
    smtp_port: Mapped[int] = mapped_column(Integer)
    smtp_security: Mapped[str] = mapped_column(String(16))  # ssl | starttls | none
    username: Mapped[str] = mapped_column(String(320))
    password_encrypted: Mapped[str] = mapped_column(Text)

    folder: Mapped[str] = mapped_column(String(200), default="INBOX")
    import_since: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    mark_as_read: Mapped[bool] = mapped_column(Boolean, default=False)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=60)
    default_category: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    uid_validity: Mapped[int | None] = mapped_column(BigInteger)
    last_uid: Mapped[int | None] = mapped_column(BigInteger)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    imported_total: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
