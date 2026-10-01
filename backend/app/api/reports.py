"""Operational reports."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import QueueReport
from app.services import ReportService

router = APIRouter(prefix="/tenants/{tenant_id}/reports", tags=["reports"])


def get_report_service(session: Annotated[Session, Depends(get_session)]) -> ReportService:
    return ReportService(session)


@router.get("/queues")
def queue_report(
    tenant_id: uuid.UUID, service: Annotated[ReportService, Depends(get_report_service)]
) -> QueueReport:
    """Case counts per queue and status (open, waiting for approval, ...)."""
    return service.queue_report(tenant_id)
