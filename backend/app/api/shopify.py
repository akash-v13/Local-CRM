"""The business's Shopify store: connect it, check it, and try the order lookup."""

import uuid
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session, sessionmaker

from app.api.connectors import get_http_client, get_resolver, get_session_factory
from app.config import Settings, get_settings
from app.db import get_session
from app.schemas import (
    ShopifyCheckResult,
    ShopifyConnectRequest,
    ShopifyInfo,
    ShopifyLookupRequest,
    ShopifyLookupResult,
    ShopifySettingsData,
)
from app.security.ssrf import Resolver
from app.services.shopify import ShopifyService

router = APIRouter(prefix="/tenants/{tenant_id}/shopify", tags=["shopify"])


def get_service(
    session: Annotated[Session, Depends(get_session)],
    http: Annotated[httpx.Client, Depends(get_http_client)],
    settings: Annotated[Settings, Depends(get_settings)],
    resolve: Annotated[Resolver, Depends(get_resolver)],
    session_factory: Annotated[sessionmaker[Session], Depends(get_session_factory)],
) -> ShopifyService:
    return ShopifyService(
        session, http=http, settings=settings, resolve=resolve, session_factory=session_factory
    )


Service = Annotated[ShopifyService, Depends(get_service)]


@router.get("")
def get_shopify(tenant_id: uuid.UUID, service: Service) -> ShopifyInfo:
    """Settings, the connected store's domain, and the fields a lookup saves."""
    return service.info(tenant_id)


@router.put("")
def save_shopify(tenant_id: uuid.UUID, body: ShopifySettingsData, service: Service) -> ShopifyInfo:
    """Turn the order lookup on/off, choose the order number field, notifications."""
    return service.save_settings(tenant_id, body)


@router.post("/connect")
def connect_shopify(
    tenant_id: uuid.UUID, body: ShopifyConnectRequest, service: Service
) -> ShopifyCheckResult:
    """Save the store's domain + app client ID/secret (encrypted, write-only) and check them."""
    return service.connect(tenant_id, body)


@router.post("/check")
def check_shopify(tenant_id: uuid.UUID, service: Service) -> ShopifyCheckResult:
    """Get an access token and read the store's name."""
    return service.check(tenant_id)


@router.post("/lookup")
def lookup_order(
    tenant_id: uuid.UUID, body: ShopifyLookupRequest, service: Service
) -> ShopifyLookupResult:
    """Look an order up now (for a case, or an order number / email). Nothing is saved."""
    return service.lookup(tenant_id, body)
