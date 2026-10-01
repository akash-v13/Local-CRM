import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAtMixin, IdMixin, JSONType, utcnow


class Job(IdMixin, CreatedAtMixin, Base):
    """A unit of background work, stored in Postgres (a simple job queue).

    The API inserts a job in the same transaction as the change that needs it
    (e.g. a new case → an "enrich_case" job), so work is never lost or started
    for a change that rolled back. The worker (app/worker.py) claims jobs with
    `SELECT ... FOR UPDATE SKIP LOCKED`, so several workers can run safely side
    by side without picking the same job.

    status: pending → running → done | failed (after max_attempts).
    """

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(40))  # e.g. "enrich_case"
    case_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
