"""Connector management and testing (Operations Portal)."""

import uuid
from collections.abc import Iterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db import SessionLocal, get_session
from app.schemas import ConnectorConfig, ConnectorRead, ConnectorTestRequest, ConnectorTestResult
from app.security.ssrf import Resolver, resolve_host
from app.services.connectors import ConnectorService, to_read

router = APIRouter(prefix="/tenants/{tenant_id}/connectors", tags=["connectors"])


def get_connector_service(session: Annotated[Session, Depends(get_session)]) -> ConnectorService:
    return ConnectorService(session)


def get_http_client() -> Iterator[httpx.Client]:
    """HTTP client for connector tests. Tests replace it with a fake transport."""
    with httpx.Client(follow_redirects=False) as client:
        yield client


def get_resolver() -> Resolver:
    """DNS resolution for the SSRF check. Tests replace it."""
    return resolve_host


def get_session_factory() -> sessionmaker[Session]:
    """For work that opens its own short sessions (token caching). Tests replace it."""
    return SessionLocal


Service = Annotated[ConnectorService, Depends(get_connector_service)]


@router.get("")
def list_connectors(tenant_id: uuid.UUID, service: Service) -> list[ConnectorRead]:
    """All connectors, in the order they run."""
    return [to_read(c) for c in service.list(tenant_id)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_connector(
    tenant_id: uuid.UUID, body: ConnectorConfig, service: Service
) -> ConnectorRead:
    return to_read(service.create(tenant_id, body))


@router.get("/{connector_id}")
def get_connector(tenant_id: uuid.UUID, connector_id: uuid.UUID, service: Service) -> ConnectorRead:
    return to_read(service.get(tenant_id, connector_id))


@router.put("/{connector_id}")
def replace_connector(
    tenant_id: uuid.UUID, connector_id: uuid.UUID, body: ConnectorConfig, service: Service
) -> ConnectorRead:
    """Replace the whole connector. Deactivate (`is_active: false`) rather than delete."""
    return to_read(service.replace(tenant_id, connector_id, body))


@router.post("/test")
def test_connector(
    tenant_id: uuid.UUID,
    body: ConnectorTestRequest,
    service: Service,
    client: Annotated[httpx.Client, Depends(get_http_client)],
    settings: Annotated[Settings, Depends(get_settings)],
    resolve: Annotated[Resolver, Depends(get_resolver)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> ConnectorTestResult:
    """Call the API for a real case with the connector as edited (saved or not).
    Returns the full response so fields can be picked. Saves nothing (apart
    from caching a generated token)."""
    return service.test(
        tenant_id,
        body,
        session_factory=session_factory,
        client=client,
        settings=settings,
        resolve=resolve,
    )
