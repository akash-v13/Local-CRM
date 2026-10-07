"""Automatic replies: send one now, cancel it, or preview a queue's standard reply."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas import AutoReplyAction, AutoReplyPreview, AutoReplyPreviewRequest
from app.services.auto_reply import AutoReplyService

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["auto-reply"])


def get_service(session: Annotated[Session, Depends(get_session)]) -> AutoReplyService:
    return AutoReplyService(session)


Service = Annotated[AutoReplyService, Depends(get_service)]


@router.post("/cases/{case_number}/auto-reply/send-now")
def send_now(
    tenant_id: uuid.UUID, case_number: int, body: AutoReplyAction, service: Service
) -> dict[str, Any]:
    """Send the scheduled automatic reply now instead of waiting (the worker sends it)."""
    case = service.send_now(tenant_id, case_number, body.actor_id)
    return dict(case.decisions.get("auto_reply") or {})


@router.post("/cases/{case_number}/auto-reply/cancel")
def cancel(
    tenant_id: uuid.UUID, case_number: int, body: AutoReplyAction, service: Service
) -> dict[str, Any]:
    """Don't send it: the person takes the case (the draft stays, to edit and send)."""
    case = service.cancel(tenant_id, case_number, body.actor_id)
    return dict(case.decisions.get("auto_reply") or {})


@router.post("/auto-reply/preview")
def preview(
    tenant_id: uuid.UUID, body: AutoReplyPreviewRequest, service: Service
) -> AutoReplyPreview:
    """A standard reply (saved or not) filled in for a real case."""
    return AutoReplyPreview(reply=service.preview(tenant_id, body.case_number, body.template))
