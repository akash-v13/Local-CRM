"""Case endpoints.

Cases are addressed by their public `case_number` (Unix microseconds), e.g.
/tenants/{tenant_id}/cases/1790812345678901.

All routes are nested under /tenants/{tenant_id}. Until authentication exists,
the tenant comes from the URL; once auth is added it must come from the
caller's token instead, and the URL value must be checked against it.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.domain.lifecycle import ALLOWED_TRANSITIONS, CaseStatus
from app.schemas import (
    CaseCreate,
    CaseDetail,
    CaseEventRead,
    CaseRead,
    EnrichRequest,
    MessageCreate,
    MessageRead,
    RerouteRequest,
    RouteRequest,
    TransitionRequest,
)
from app.services import CaseService

router = APIRouter(prefix="/tenants/{tenant_id}/cases", tags=["cases"])


def get_case_service(session: Annotated[Session, Depends(get_session)]) -> CaseService:
    return CaseService(session)


Service = Annotated[CaseService, Depends(get_case_service)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_case(tenant_id: uuid.UUID, body: CaseCreate, service: Service) -> CaseRead:
    """Intake a new case (webform, email, helpdesk add-on, ...)."""
    return CaseRead.model_validate(service.create_case(tenant_id, body))


@router.get("")
def list_cases(
    tenant_id: uuid.UUID,
    service: Service,
    status_filter: Annotated[CaseStatus | None, Query(alias="status")] = None,
    queue_id: uuid.UUID | None = None,
    unrouted: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[CaseRead]:
    """List cases, newest first. Filter by status, by queue, or `unrouted=true`."""
    cases = service.list_cases(tenant_id, status_filter, queue_id, unrouted, limit, offset)
    return [CaseRead.model_validate(c) for c in cases]


@router.get("/{case_number}")
def get_case(tenant_id: uuid.UUID, case_number: int, service: Service) -> CaseDetail:
    """Get one case with its full message thread and allowed next statuses."""
    case = service.get_case(tenant_id, case_number)
    messages = [
        MessageRead.model_validate(m) for m in service.list_messages(tenant_id, case_number)
    ]
    allowed = ALLOWED_TRANSITIONS[CaseStatus(case.status)]
    return CaseDetail(
        **CaseRead.model_validate(case).model_dump(),
        messages=messages,
        # Listed in lifecycle order, so UI buttons appear in a stable, sensible order.
        allowed_next_statuses=[s for s in CaseStatus if s in allowed],
    )


@router.post("/{case_number}/messages", status_code=status.HTTP_201_CREATED)
def add_message(
    tenant_id: uuid.UUID, case_number: int, body: MessageCreate, service: Service
) -> MessageRead:
    """Add an agent reply, an internal note, or a simulated customer reply."""
    return MessageRead.model_validate(service.add_message(tenant_id, case_number, body))


@router.post("/{case_number}/transitions")
def transition_case(
    tenant_id: uuid.UUID, case_number: int, body: TransitionRequest, service: Service
) -> CaseRead:
    """Change a case's status. Rejected with 409 if the lifecycle doesn't allow it."""
    return CaseRead.model_validate(service.transition(tenant_id, case_number, body))


@router.get("/{case_number}/events")
def list_case_events(
    tenant_id: uuid.UUID, case_number: int, service: Service
) -> list[CaseEventRead]:
    """The case's audit trail, oldest first."""
    return [CaseEventRead.model_validate(e) for e in service.list_events(tenant_id, case_number)]


@router.post("/{case_number}/route")
def route_case(
    tenant_id: uuid.UUID, case_number: int, body: RouteRequest, service: Service
) -> CaseRead:
    """Re-run queue matching (Intake/Queued cases that aren't pinned)."""
    return CaseRead.model_validate(service.route_case(tenant_id, case_number, body))


@router.post("/{case_number}/reroute")
def reroute_case(
    tenant_id: uuid.UUID, case_number: int, body: RerouteRequest, service: Service
) -> CaseRead:
    """Manually move a case to a queue. Pins it there (automatic routing won't move it)."""
    return CaseRead.model_validate(service.reroute(tenant_id, case_number, body))


@router.post("/{case_number}/enrich")
def enrich_case(
    tenant_id: uuid.UUID, case_number: int, body: EnrichRequest, service: Service
) -> CaseRead:
    """Queue the connectors to run again for this case (e.g. after EnrichmentFailed)."""
    return CaseRead.model_validate(service.enrich(tenant_id, case_number, body))
