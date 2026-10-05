"""Compensation matrix: rules, guardrail settings, live test, backtest, and decisions on cases."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import (
    CompensationDecisionData,
    CompensationPreview,
    CompensationPreviewRequest,
    CompensationReview,
    CompensationRuleCreate,
    CompensationRuleRead,
    CompensationSettingsData,
    DecideRequest,
    SimulationRequest,
    SimulationResult,
)
from app.services.compensation import CompensationService

router = APIRouter(prefix="/tenants/{tenant_id}/compensation", tags=["compensation"])
case_router = APIRouter(
    prefix="/tenants/{tenant_id}/cases/{case_number}/compensation", tags=["compensation"]
)


def get_service(session: Annotated[Session, Depends(get_session)]) -> CompensationService:
    return CompensationService(session)


Service = Annotated[CompensationService, Depends(get_service)]


@router.get("/rules")
def list_rules(tenant_id: uuid.UUID, service: Service) -> list[CompensationRuleRead]:
    """All rules, active and inactive, in decision order (priority, then age)."""
    return [CompensationRuleRead.model_validate(r) for r in service.list_rules(tenant_id)]


@router.post("/rules", status_code=status.HTTP_201_CREATED)
def create_rule(
    tenant_id: uuid.UUID, body: CompensationRuleCreate, service: Service
) -> CompensationRuleRead:
    return CompensationRuleRead.model_validate(service.save_rule(tenant_id, body))


@router.get("/rules/{rule_id}")
def get_rule(tenant_id: uuid.UUID, rule_id: uuid.UUID, service: Service) -> CompensationRuleRead:
    return CompensationRuleRead.model_validate(service.get_rule(tenant_id, rule_id))


@router.put("/rules/{rule_id}")
def replace_rule(
    tenant_id: uuid.UUID, rule_id: uuid.UUID, body: CompensationRuleCreate, service: Service
) -> CompensationRuleRead:
    """Replace a rule. Rules are deactivated (`is_active: false`), never deleted.
    Decisions already made on cases don't change."""
    return CompensationRuleRead.model_validate(service.save_rule(tenant_id, body, rule_id))


@router.get("/settings")
def get_settings(tenant_id: uuid.UUID, service: Service) -> CompensationSettingsData:
    return service.get_settings(tenant_id)


@router.put("/settings")
def save_settings(
    tenant_id: uuid.UUID, body: CompensationSettingsData, service: Service
) -> CompensationSettingsData:
    """Repeat-claimant check and default currency."""
    return service.save_settings(tenant_id, body)


@router.post("/preview")
def preview(
    tenant_id: uuid.UUID, body: CompensationPreviewRequest, service: Service
) -> CompensationPreview:
    """What would the matrix decide for a case, optionally with an unsaved rule?
    Explains every rule's result. Changes nothing."""
    return service.preview(tenant_id, body)


@router.post("/simulate")
def simulate(tenant_id: uuid.UUID, body: SimulationRequest, service: Service) -> SimulationResult:
    """Backtest the matrix (optionally with an unsaved rule) on recent cases. Changes nothing."""
    return service.simulate(tenant_id, body)


@case_router.post("/decide")
def decide_again(
    tenant_id: uuid.UUID, case_number: int, body: DecideRequest, service: Service
) -> CompensationDecisionData:
    """Run the matrix for this case again (e.g. after enrichment or rule changes).
    Not allowed once a person has approved or rejected the decision."""
    return service.decide_again(tenant_id, case_number, body.actor_id)


@case_router.post("/approve")
def approve(
    tenant_id: uuid.UUID, case_number: int, body: CompensationReview, service: Service
) -> CompensationDecisionData:
    return service.review(tenant_id, case_number, body, approve=True)


@case_router.post("/reject")
def reject(
    tenant_id: uuid.UUID, case_number: int, body: CompensationReview, service: Service
) -> CompensationDecisionData:
    """Reject a pending decision; `note` (the reason) is required."""
    return service.review(tenant_id, case_number, body, approve=False)
