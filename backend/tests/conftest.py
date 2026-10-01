"""Test fixtures.

Tests run against an in-memory SQLite database, so they need no Docker or
Postgres and finish in seconds. The API's `get_session` dependency is swapped
for one that uses this test database, and outbound HTTP for connectors is
replaced with a fake transport (no real network calls in tests).

Trade-off: SQLite is not Postgres. Anything Postgres-specific (JSONB queries,
locking behaviour, the migrations themselves) is checked against a real
Postgres in CI — see docs/dev/database-guide.md.
"""

from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.connectors import get_http_client, get_resolver
from app.db import get_session
from app.main import app
from app.models import Base

# Every hostname "resolves" to a public address unless a test says otherwise.
PUBLIC_IP = "93.184.216.34"


def public_resolver(host: str, port: int) -> list[str]:
    return [PUBLIC_IP]


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    # StaticPool + one shared connection keeps the in-memory DB alive across sessions.
    engine = create_engine(
        "sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    engine.dispose()


Handler = Callable[[httpx.Request], httpx.Response]


class FakeApis:
    """Stand-in for external APIs. Tests set `handler` to decide each response."""

    def __init__(self) -> None:
        self.handler: Handler = lambda request: httpx.Response(404)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.handler(request)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self), follow_redirects=False)


@pytest.fixture
def fake_apis() -> FakeApis:
    return FakeApis()


@pytest.fixture
def client(session_factory: sessionmaker[Session], fake_apis: FakeApis) -> Iterator[TestClient]:
    def override_get_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    def override_http_client() -> Iterator[httpx.Client]:
        with fake_apis.client() as http:
            yield http

    app.dependency_overrides[get_session] = override_get_session
    app.dependency_overrides[get_http_client] = override_http_client
    app.dependency_overrides[get_resolver] = lambda: public_resolver
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def tenant_id(client: TestClient) -> str:
    response = client.post("/tenants", json={"name": "Acme Store"})
    assert response.status_code == 201
    return str(response.json()["id"])
