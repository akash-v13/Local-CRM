"""Queue management and routing tools, used by the Operations Portal."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import (
    QueueCreate,
    QueueRead,
    QueueUpdate,
    RoutingFields,
    RoutingPreview,
    RoutingPreviewRequest,
)
from app.services import QueueService

router = APIRouter(prefix="/tenants/{tenant_id}/queues", tags=["queues"])
routing_router = APIRouter(prefix="/tenants/{tenant_id}/routing", tags=["routing"])


def get_queue_service(session: Annotated[Session, Depends(get_session)]) -> QueueService:
    return QueueService(session)


Service = Annotated[QueueService, Depends(get_queue_service)]


@router.get("")
def list_queues(tenant_id: uuid.UUID, service: Service) -> list[QueueRead]:
    """All queues, active and inactive, in routing order (priority, then age)."""
    return [QueueRead.model_validate(q) for q in service.list(tenant_id)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_queue(tenant_id: uuid.UUID, body: QueueCreate, service: Service) -> QueueRead:
    return QueueRead.model_validate(service.create(tenant_id, body))


@router.get("/{queue_id}")
def get_queue(tenant_id: uuid.UUID, queue_id: uuid.UUID, service: Service) -> QueueRead:
    return QueueRead.model_validate(service.get(tenant_id, queue_id))


@router.patch("/{queue_id}")
def update_queue(
    tenant_id: uuid.UUID, queue_id: uuid.UUID, body: QueueUpdate, service: Service
) -> QueueRead:
    """Partial update. Queues are deactivated (`is_active: false`), never deleted,
    so historical cases keep pointing at them."""
    return QueueRead.model_validate(service.update(tenant_id, queue_id, body))


@routing_router.get("/fields")
def routing_fields(tenant_id: uuid.UUID, service: Service) -> RoutingFields:
    """Fields, suggested values and operators for the condition builder."""
    return service.fields(tenant_id)


@routing_router.post("/preview")
def routing_preview(
    tenant_id: uuid.UUID, body: RoutingPreviewRequest, service: Service
) -> RoutingPreview:
    """Which queue would this case land in, and why? Optionally with unsaved queue edits."""
    return service.preview(tenant_id, body)
