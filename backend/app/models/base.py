"""Shared building blocks for all database models (tables).

Coming from a document database: each model class here is a **table** (the
equivalent of a collection), each instance is a **row** (a document).
Flexible, schema-less parts of a record live in JSON columns (`JSONType`),
which are stored as Postgres `JSONB` — you keep document-style flexibility
where you need it and strict columns where you want guarantees.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, MetaData, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# JSONB on Postgres, plain JSON elsewhere (the test suite runs on SQLite).
# `MutableDict` makes top-level changes like `case.flags["sensitive"] = True`
# get saved. NOTE: changes to *nested* dicts are NOT detected — reassign the
# whole value instead: `case.enrichment = {**case.enrichment, "order": {...}}`.
JSONType = MutableDict.as_mutable(JSON().with_variant(JSONB(), "postgresql"))

# Predictable constraint names, so Alembic migrations are stable and readable.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    """Current time in UTC. Always store timestamps in UTC; convert for display only."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class IdMixin:
    """Random UUID primary key, generated in Python when the row is first flushed."""

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
