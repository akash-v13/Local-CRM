"""Linked email inboxes (Operations Portal → Email) and retrying a failed email."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.db import get_session
from app.domain.errors import NotFoundError
from app.email.transport import MailTransport
from app.repositories import CaseRepository
from app.schemas import (
    MailboxRead,
    MailboxRecentCase,
    MailboxTestRequest,
    MailboxTestResult,
    MailboxWrite,
    MessageRead,
)
from app.services.email import MailboxService, retry_send, transport_from

router = APIRouter(prefix="/tenants/{tenant_id}/mailboxes", tags=["email"])
case_router = APIRouter(prefix="/tenants/{tenant_id}/cases/{case_number}", tags=["email"])


def get_mail_transport(settings: Annotated[Settings, Depends(get_settings)]) -> MailTransport:
    """IMAP/SMTP client. Tests override this with a fake."""
    return transport_from(settings)


def get_service(
    session: Annotated[Session, Depends(get_session)],
    transport: Annotated[MailTransport, Depends(get_mail_transport)],
) -> MailboxService:
    return MailboxService(session, transport)


Service = Annotated[MailboxService, Depends(get_service)]


@router.get("")
def list_mailboxes(tenant_id: uuid.UUID, service: Service) -> list[MailboxRead]:
    return [MailboxRead.model_validate(m) for m in service.list_mailboxes(tenant_id)]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_mailbox(tenant_id: uuid.UUID, body: MailboxWrite, service: Service) -> MailboxRead:
    """Link an inbox. Emails received from now on (or `backfill_days` back) become cases.
    The password is stored encrypted and never returned."""
    return MailboxRead.model_validate(service.save(tenant_id, body))


@router.post("/test")
def test_mailbox(
    tenant_id: uuid.UUID, body: MailboxTestRequest, service: Service
) -> MailboxTestResult:
    """Sign in to IMAP and SMTP with unsaved settings. Nothing is saved or imported."""
    return service.test(tenant_id, body.draft, body.mailbox_id)


@router.get("/{mailbox_id}")
def get_mailbox(tenant_id: uuid.UUID, mailbox_id: uuid.UUID, service: Service) -> MailboxRead:
    return MailboxRead.model_validate(service.get(tenant_id, mailbox_id))


@router.put("/{mailbox_id}")
def replace_mailbox(
    tenant_id: uuid.UUID, mailbox_id: uuid.UUID, body: MailboxWrite, service: Service
) -> MailboxRead:
    """Replace an inbox's settings. Omit `password` to keep the stored one.
    Deactivate (`is_active: false`) to stop importing; cases keep their history."""
    return MailboxRead.model_validate(service.save(tenant_id, body, mailbox_id))


@router.post("/{mailbox_id}/check")
def check_now(tenant_id: uuid.UUID, mailbox_id: uuid.UUID, service: Service) -> MailboxRead:
    """Check for new email right away (the worker runs it within seconds)."""
    return MailboxRead.model_validate(service.check_now(tenant_id, mailbox_id))


@router.get("/{mailbox_id}/recent")
def recent_cases(
    tenant_id: uuid.UUID, mailbox_id: uuid.UUID, service: Service
) -> list[MailboxRecentCase]:
    """The latest cases created from this inbox."""
    return service.recent_cases(tenant_id, mailbox_id)


@case_router.post("/messages/{message_id}/retry-send")
def retry_failed_email(
    tenant_id: uuid.UUID,
    case_number: int,
    message_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
) -> MessageRead:
    """Send a failed email again (e.g. after fixing the inbox password)."""
    case = CaseRepository(session).get_by_number(tenant_id, case_number)
    if case is None:
        raise NotFoundError(f"Case {case_number} not found.")
    return MessageRead.model_validate(retry_send(session, tenant_id, case, message_id))
