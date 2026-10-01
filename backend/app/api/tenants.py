import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.taxonomy import DEFAULT_TAXONOMY, CaseType
from app.schemas import TenantCreate, TenantRead
from app.services import TenantService

router = APIRouter(prefix="/tenants", tags=["tenants"])


def get_tenant_service(session: Annotated[Session, Depends(get_session)]) -> TenantService:
    return TenantService(session)


Service = Annotated[TenantService, Depends(get_tenant_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_tenant(body: TenantCreate, service: Service) -> TenantRead:
    """Create a tenant. For local development until sign-up and auth exist."""
    return TenantRead.model_validate(service.create(body))


@router.get("")
def list_tenants(service: Service) -> list[TenantRead]:
    """List all tenants. Development only: lets the UI offer a tenant picker."""
    return [TenantRead.model_validate(t) for t in service.list()]


@router.get("/{tenant_id}/categories")
def list_categories(tenant_id: uuid.UUID, service: Service) -> list[CaseType]:
    """Case taxonomy (Type → Category → Subcategory) for webform dropdowns."""
    service.get(tenant_id)  # 404 for unknown tenants
    return DEFAULT_TAXONOMY
