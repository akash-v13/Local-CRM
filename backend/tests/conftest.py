"""Test fixtures.

Tests run against an in-memory SQLite database, so they need no Docker or
Postgres and finish in seconds. The API's `get_session` dependency is swapped
for one that uses this test database.

Trade-off: SQLite is not Postgres. Anything Postgres-specific (JSONB queries,
locking behaviour, the migrations themselves) must be checked against a real
Postgres — see docs/dev/database-guide.md.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_session
from app.main import app
from app.models import Base


@pytest.fixture
def client() -> Iterator[TestClient]:
    # StaticPool + one shared connection keeps the in-memory DB alive across sessions.
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_session() -> Iterator[Session]:
        with TestSession() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def tenant_id(client: TestClient) -> str:
    response = client.post("/tenants", json={"name": "Acme Store"})
    assert response.status_code == 201
    return str(response.json()["id"])
