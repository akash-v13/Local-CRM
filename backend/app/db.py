"""Database engine and session management.

- The **engine** holds the connection pool. There is one per process.
- A **session** is a unit of work: you load/modify objects, then `commit()` to
  write everything in one transaction (or it all rolls back on error).

FastAPI routes get a session through the `get_session` dependency. The session
is closed automatically after the request; anything not committed is rolled back.
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

# `pool_pre_ping` checks a connection is still alive before using it, which
# avoids errors after the database restarts or idle connections are dropped.
engine = create_engine(get_settings().database_url, pool_pre_ping=True)

# `expire_on_commit=False` keeps objects readable after commit, so a service can
# commit and then return the object to the API layer for serialization.
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency that yields a session and always closes it."""
    with SessionLocal() as session:
        yield session
