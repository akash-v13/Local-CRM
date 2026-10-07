"""Setting a business up for where it sells, and one view of everything it connected."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.schemas import BusinessProfile, IntegrationsInfo, SetupInfo
from app.services.setup import SetupService

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["setup"])


def get_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SetupService:
    return SetupService(session, settings)


Service = Annotated[SetupService, Depends(get_service)]


@router.get("/setup")
def get_setup(tenant_id: uuid.UUID, service: Service) -> SetupInfo:
    """Where the business sells, and its setup checklist (ticked from real settings)."""
    return service.info(tenant_id)


@router.put("/setup")
def save_setup(tenant_id: uuid.UUID, body: BusinessProfile, service: Service) -> SetupInfo:
    """Save where the business sells. Switches on reading order numbers from emails if
    it isn't configured yet (listed in `applied`)."""
    return service.save(tenant_id, body)


@router.get("/integrations")
def get_integrations(tenant_id: uuid.UUID, service: Service) -> IntegrationsInfo:
    """Store platforms, messages, payments and the business's own systems, with status."""
    return service.integrations(tenant_id)
