"""The intake pipeline: the business-wide flow, and what happened to each case."""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import ExecutionDetail, ExecutionSummary, PipelineDefinition
from app.services.pipeline import PipelineService

router = APIRouter(prefix="/tenants/{tenant_id}/pipeline", tags=["pipeline"])


def get_service(session: Annotated[Session, Depends(get_session)]) -> PipelineService:
    return PipelineService(session)


Service = Annotated[PipelineService, Depends(get_service)]


@router.get("")
def pipeline(tenant_id: uuid.UUID, service: Service) -> PipelineDefinition:
    """What every new case goes through: connectors in run order (with the data each
    one uses from earlier steps, and setup problems), then routing, then compensation."""
    return service.definition(tenant_id)


@router.get("/executions")
def executions(
    tenant_id: uuid.UUID,
    service: Service,
    outcome: Literal["ok", "partial", "failed", "in_progress", "no_enrichment"] | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ExecutionSummary]:
    """Recent cases' runs through the pipeline, newest first."""
    return service.executions(tenant_id, outcome=outcome, limit=limit)


@router.get("/executions/{case_number}")
def execution(tenant_id: uuid.UUID, case_number: int, service: Service) -> ExecutionDetail:
    """One case's run: each step's status, request, data and timing; routing; compensation."""
    return service.execution(tenant_id, case_number)
