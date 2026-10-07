"""Payouts: issuing approved compensation through the business's Stripe account."""

import uuid
from collections.abc import Iterator
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.schemas import (
    PayoutListRow,
    PayoutRead,
    PayoutRequest,
    PayoutSettingsData,
    StripeCheckRequest,
    StripeCheckResult,
)
from app.services.payouts import PayoutService

router = APIRouter(prefix="/tenants/{tenant_id}/payouts", tags=["payouts"])
case_router = APIRouter(prefix="/tenants/{tenant_id}/cases/{case_number}/payouts", tags=["payouts"])


def get_payout_http() -> Iterator[httpx.Client]:
    """HTTP client for Stripe (tests override this with a fake Stripe)."""
    with httpx.Client(follow_redirects=False) as client:
        yield client


def get_service(
    session: Annotated[Session, Depends(get_session)],
    http: Annotated[httpx.Client, Depends(get_payout_http)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PayoutService:
    return PayoutService(session, http, settings.stripe_api_base)


Service = Annotated[PayoutService, Depends(get_service)]


@router.get("/settings")
def get_payout_settings(tenant_id: uuid.UUID, service: Service) -> PayoutSettingsData:
    return service.get_settings(tenant_id)


@router.put("/settings")
def save_payout_settings(
    tenant_id: uuid.UUID, body: PayoutSettingsData, service: Service
) -> PayoutSettingsData:
    """Which credential holds the Stripe key, how each compensation type is issued,
    how to find an order's payment, voucher settings, and whether to pay automatically."""
    return service.save_settings(tenant_id, body)


@router.post("/check-stripe")
def check_stripe(
    tenant_id: uuid.UUID, body: StripeCheckRequest, service: Service
) -> StripeCheckResult:
    """Sign in to Stripe with a credential: is the key valid, and is it test or live mode?"""
    return service.check_stripe(tenant_id, body.credential_id)


@router.get("")
def list_payouts(
    tenant_id: uuid.UUID, service: Service, status: str | None = None
) -> list[PayoutListRow]:
    """Recent payouts, newest first."""
    return service.list_payouts(tenant_id, status)


@case_router.get("")
def case_payouts(tenant_id: uuid.UUID, case_number: int, service: Service) -> list[PayoutRead]:
    return [PayoutRead.model_validate(p) for p in service.case_payouts(tenant_id, case_number)]


@case_router.post("", status_code=status.HTTP_201_CREATED)
def pay_now(
    tenant_id: uuid.UUID, case_number: int, body: PayoutRequest, service: Service
) -> PayoutRead:
    """Issue the case's approved compensation now (when automatic payouts are off), or
    retry one that failed after fixing the cause. Never pays the same decision twice."""
    return PayoutRead.model_validate(service.pay_now(tenant_id, case_number, body.actor_id))
