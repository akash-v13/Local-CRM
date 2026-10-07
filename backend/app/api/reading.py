"""Reading customer messages: settings, a test panel, and agent review on cases."""

import uuid
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.ai.readers import Reader, reader_from
from app.ai.reading import PATTERN_PRESETS
from app.config import Settings, get_settings
from app.db import get_session
from app.schemas import (
    CaseRead,
    CategoryChange,
    FieldReview,
    ReadingPreviewRequest,
    ReadingSettingsData,
)
from app.services.reading import ReadingService

router = APIRouter(prefix="/tenants/{tenant_id}/reading", tags=["reading"])
case_router = APIRouter(prefix="/tenants/{tenant_id}/cases/{case_number}", tags=["reading"])


def get_reader(settings: Annotated[Settings, Depends(get_settings)]) -> Reader | None:
    """Jev, Claude, or None (patterns only). Tests override this."""
    return reader_from(settings, httpx.Client(follow_redirects=False))


def get_service(
    session: Annotated[Session, Depends(get_session)],
    reader: Annotated[Reader | None, Depends(get_reader)],
) -> ReadingService:
    return ReadingService(session, reader)


Service = Annotated[ReadingService, Depends(get_service)]


def _info(service: ReadingService, settings: ReadingSettingsData) -> dict[str, Any]:
    return {
        "settings": settings.model_dump(),
        "reader": service.reader_name(),
        "presets": [
            {"id": key, "pattern": pattern, "description": description}
            for key, (pattern, description) in PATTERN_PRESETS.items()
        ],
    }


@router.get("")
def get_reading(tenant_id: uuid.UUID, service: Service) -> dict[str, Any]:
    """Settings, which model reads messages (jev / claude / patterns), and pattern presets."""
    return _info(service, service.get_settings(tenant_id))


@router.put("")
def save_reading(
    tenant_id: uuid.UUID, body: ReadingSettingsData, service: Service
) -> dict[str, Any]:
    return _info(service, service.save_settings(tenant_id, body))


@router.post("/preview")
def preview(tenant_id: uuid.UUID, body: ReadingPreviewRequest, service: Service) -> dict[str, Any]:
    """Read a pasted message or a real case with saved or unsaved settings. Nothing is saved."""
    return service.preview(tenant_id, body)


@case_router.post("/extraction/fields/{key}")
def confirm_field(
    tenant_id: uuid.UUID, case_number: int, key: str, body: FieldReview, service: Service
) -> CaseRead:
    """Set a field the reader wasn't sure about (e.g. pick the right order number)."""
    return CaseRead.model_validate(service.confirm_field(tenant_id, case_number, key, body))


@case_router.post("/category")
def change_category(
    tenant_id: uuid.UUID, case_number: int, body: CategoryChange, service: Service
) -> CaseRead:
    """Set the case's category (e.g. apply the reader's suggestion). Re-run routing after."""
    return CaseRead.model_validate(service.change_category(tenant_id, case_number, body))
