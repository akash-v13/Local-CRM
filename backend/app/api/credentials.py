"""Credentials: shared authentication for connectors (Operations Portal)."""

import uuid
from collections.abc import Iterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session, sessionmaker

from app.api.connectors import get_http_client, get_resolver, get_session_factory
from app.config import Settings, get_settings
from app.db import get_session
from app.schemas import CredentialRead, CredentialWrite, TokenTestResult
from app.security.ssrf import Resolver
from app.services.connectors import run_settings
from app.services.credentials import CredentialService

router = APIRouter(prefix="/tenants/{tenant_id}/credentials", tags=["credentials"])


def get_credential_service(
    session: Annotated[Session, Depends(get_session)],
) -> Iterator[CredentialService]:
    yield CredentialService(session)


Service = Annotated[CredentialService, Depends(get_credential_service)]


@router.get("")
def list_credentials(tenant_id: uuid.UUID, service: Service) -> list[CredentialRead]:
    return [service.to_read(c) for c in service.list(tenant_id)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_credential(
    tenant_id: uuid.UUID, body: CredentialWrite, service: Service
) -> CredentialRead:
    """Create a credential. Secret values are encrypted and never returned."""
    return service.to_read(service.create(tenant_id, body))


@router.get("/{credential_id}")
def get_credential(
    tenant_id: uuid.UUID, credential_id: uuid.UUID, service: Service
) -> CredentialRead:
    return service.to_read(service.get(tenant_id, credential_id))


@router.put("/{credential_id}")
def replace_credential(
    tenant_id: uuid.UUID, credential_id: uuid.UUID, body: CredentialWrite, service: Service
) -> CredentialRead:
    """Replace settings. Omit `secrets` to keep the stored values. Drops any cached token."""
    return service.to_read(service.replace(tenant_id, credential_id, body))


@router.post("/{credential_id}/test")
def test_credential(
    tenant_id: uuid.UUID,
    credential_id: uuid.UUID,
    service: Service,
    client: Annotated[httpx.Client, Depends(get_http_client)],
    settings: Annotated[Settings, Depends(get_settings)],
    resolve: Annotated[Resolver, Depends(get_resolver)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> TokenTestResult:
    """Token kinds: generate a fresh token now and cache it. Others: check the secrets."""
    return service.test_token(
        tenant_id,
        credential_id,
        session_factory=session_factory,
        client=client,
        settings=run_settings(settings, resolve),
    )
