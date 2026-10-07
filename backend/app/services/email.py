"""Email channel: linked inboxes, importing emails into cases, and sending replies.

    customer email ──IMAP──► poll_mailbox job ──► new case, or a reply on its case
    agent reply on an email case ──► send_email job ──SMTP──► customer

Importing (worker job `poll_mailbox`, scheduled per inbox by `schedule_polls`):
1. Read the inbox settings, then close the database session.
2. Fetch new messages over IMAP (no database connection held while waiting).
3. Each message in its own transaction:
   - skipped if it's from the inbox itself, automatic (auto-reply, bounce,
     mailing list, no-reply sender) or older than `import_since`;
   - skipped if its Message-ID was already imported (also enforced by a unique index);
   - added to an existing case when it replies to one of the case's emails
     (In-Reply-To / References), or carries the case's "[Case N]" subject token
     *and* comes from that case's customer;
   - otherwise a new case (channel "email") with the subject in `attributes.subject`.
   A reply to a closed case opens a new case linked to it (`attributes.relatedCase`).
4. The inbox's position (last UID) and status are saved as it goes.

Sending (worker job `send_email`, queued by `CaseService.add_message` for agent
replies on email cases): the reply is built with proper threading headers so it
lands in the customer's existing conversation. Delivery status lives on the
message (`email.delivery`); failures retry with backoff, then show as failed.
Delivery is at-least-once: a crash between the SMTP send and saving the status
could resend once; a sent status is checked before every attempt.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, formataddr, make_msgid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.domain.errors import ConflictError, NotFoundError
from app.domain.lifecycle import CaseStatus
from app.email.parse import ParsedEmail, case_number_in, parse_email, reply_subject, strip_quoted
from app.email.transport import (
    ConnectionCheck,
    FetchedMessage,
    ImapSmtpTransport,
    MailAccount,
    MailError,
    MailServer,
    MailTransport,
    TransportSettings,
)
from app.models import Case, CaseEvent, Job, Mailbox, Message, Tenant
from app.models.base import utcnow
from app.repositories import CaseRepository, TenantRepository
from app.schemas import (
    CaseCreate,
    CategoryIn,
    CustomerIn,
    MailboxRecentCase,
    MailboxTestResult,
    MailboxWrite,
    MessageCreate,
)
from app.security.secrets import decrypt_secret, encrypt_secret

FETCH_BATCH = 50  # messages per poll; the next poll continues where this one stopped
CLOCK_SLACK = timedelta(minutes=5)


def transport_from(settings: Settings) -> ImapSmtpTransport:
    return ImapSmtpTransport(
        TransportSettings(
            allowed_hosts=settings.email_allowed_hosts,
            allow_insecure=settings.email_allow_insecure,
            timeout=settings.email_timeout_seconds,
        )
    )


def account_for(mailbox: Mailbox, password: str | None = None) -> MailAccount:
    return MailAccount(
        address=mailbox.address,
        username=mailbox.username,
        password=password if password is not None else decrypt_secret(mailbox.password_encrypted),
        imap=MailServer(mailbox.imap_host, mailbox.imap_port, mailbox.imap_security),  # type: ignore[arg-type]
        smtp=MailServer(mailbox.smtp_host, mailbox.smtp_port, mailbox.smtp_security),  # type: ignore[arg-type]
        folder=mailbox.folder,
    )


@dataclass(frozen=True)
class InboundEmail:
    """Email details attached to an inbound message (see CaseService)."""

    external_id: str
    meta: dict[str, Any]
    mailbox_id: uuid.UUID


# ----- managing inboxes ------------------------------------------------------------------


class MailboxService:
    def __init__(self, session: Session, transport: MailTransport) -> None:
        self.session = session
        self.transport = transport
        self.tenants = TenantRepository(session)

    def _require_tenant(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        return tenant

    def list_mailboxes(self, tenant_id: uuid.UUID) -> Sequence[Mailbox]:
        self._require_tenant(tenant_id)
        stmt = select(Mailbox).where(Mailbox.tenant_id == tenant_id).order_by(Mailbox.name)
        return self.session.scalars(stmt).all()

    def get(self, tenant_id: uuid.UUID, mailbox_id: uuid.UUID) -> Mailbox:
        stmt = select(Mailbox).where(Mailbox.tenant_id == tenant_id, Mailbox.id == mailbox_id)
        mailbox = self.session.scalars(stmt).one_or_none()
        if mailbox is None:
            raise NotFoundError(f"Inbox {mailbox_id} not found.")
        return mailbox

    def save(
        self, tenant_id: uuid.UUID, data: MailboxWrite, mailbox_id: uuid.UUID | None = None
    ) -> Mailbox:
        """Create an inbox (importing from now, or `backfill_days` back), or replace one.
        Changing the server, account or folder restarts the import position."""
        self._require_tenant(tenant_id)
        if mailbox_id is None:
            if not data.password:
                raise ConflictError("Enter the inbox's (app) password.")
            mailbox = Mailbox(
                tenant_id=tenant_id,
                import_since=utcnow() - timedelta(days=data.backfill_days),
                imported_total=0,
            )
        else:
            mailbox = self.get(tenant_id, mailbox_id)
        values = data.model_dump(exclude={"password", "backfill_days", "default_category"})
        position_changed = mailbox_id is not None and any(
            getattr(mailbox, k) != values[k] for k in ("imap_host", "username", "folder")
        )
        for key, value in values.items():
            setattr(mailbox, key, value)
        mailbox.address = str(data.address).lower()
        mailbox.default_category = (
            data.default_category.model_dump() if data.default_category else None
        )
        if data.password:
            mailbox.password_encrypted = encrypt_secret(data.password)
        if position_changed:
            mailbox.uid_validity = mailbox.last_uid = None
        mailbox.updated_at = utcnow()
        if mailbox_id is None:
            self.session.add(mailbox)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ConflictError(f"{data.address} is already linked.") from exc
        return mailbox

    def test(
        self, tenant_id: uuid.UUID, data: MailboxWrite, mailbox_id: uuid.UUID | None
    ) -> MailboxTestResult:
        """Sign in to IMAP and SMTP with unsaved settings. Nothing is saved or imported."""
        self._require_tenant(tenant_id)
        password = data.password
        if not password and mailbox_id is not None:
            password = decrypt_secret(self.get(tenant_id, mailbox_id).password_encrypted)
        if not password:
            raise ConflictError("Enter the inbox's (app) password to test it.")
        draft = Mailbox(
            **data.model_dump(exclude={"password", "backfill_days", "default_category"})
        )
        draft.address = str(data.address).lower()
        result: ConnectionCheck = self.transport.test(account_for(draft, password))
        return MailboxTestResult(**result.__dict__)

    def check_now(self, tenant_id: uuid.UUID, mailbox_id: uuid.UUID) -> Mailbox:
        """Queue a poll right away (unless one is already waiting)."""
        mailbox = self.get(tenant_id, mailbox_id)
        if mailbox_id not in _queued_polls(self.session):
            self.session.add(
                Job(
                    tenant_id=tenant_id,
                    kind="poll_mailbox",
                    payload={"mailbox_id": str(mailbox.id)},
                )
            )
            self.session.commit()
        return mailbox

    def recent_cases(self, tenant_id: uuid.UUID, mailbox_id: uuid.UUID) -> list[MailboxRecentCase]:
        self.get(tenant_id, mailbox_id)
        stmt = (
            select(Case)
            .where(Case.tenant_id == tenant_id, Case.mailbox_id == mailbox_id)
            .order_by(Case.case_number.desc())
            .limit(20)
        )
        return [
            MailboxRecentCase(
                case_number=c.case_number,
                created_at=c.created_at,
                status=c.status,
                customer_email=c.customer.email,
                subject=c.attributes.get("subject"),
            )
            for c in self.session.scalars(stmt)
        ]


def _queued_polls(session: Session) -> set[uuid.UUID]:
    stmt = select(Job.payload).where(
        Job.kind == "poll_mailbox", Job.status.in_(("pending", "running"))
    )
    payloads: Sequence[dict[str, Any]] = session.scalars(stmt).all()
    return {uuid.UUID(p["mailbox_id"]) for p in payloads if p.get("mailbox_id")}


def schedule_polls(session_factory: sessionmaker[Session]) -> int:
    """Queue a poll for every active inbox that's due. Called by the worker loop."""
    now = utcnow()
    with session_factory() as session:
        queued = _queued_polls(session)
        added = 0
        for mailbox in session.scalars(select(Mailbox).where(Mailbox.is_active.is_(True))):
            due = mailbox.last_checked_at is None or (
                _aware(mailbox.last_checked_at) + timedelta(seconds=mailbox.poll_interval_seconds)
                <= now
            )
            if due and mailbox.id not in queued:
                session.add(
                    Job(
                        tenant_id=mailbox.tenant_id,
                        kind="poll_mailbox",
                        payload={"mailbox_id": str(mailbox.id)},
                        max_attempts=1,  # the next scheduled poll is the retry
                    )
                )
                added += 1
        session.commit()
        return added


def _aware(value: datetime) -> datetime:
    """SQLite (tests) returns naive datetimes; Postgres returns aware ones."""
    from datetime import UTC

    return value if value.tzinfo else value.replace(tzinfo=UTC)


# ----- importing -------------------------------------------------------------------------


def _meta(parsed: ParsedEmail, mailbox: Mailbox) -> dict[str, Any]:
    return {
        "subject": parsed.subject,
        "from": parsed.from_address,
        "from_name": parsed.from_name,
        "to": parsed.to,
        "cc": parsed.cc,
        "date": parsed.date.isoformat() if parsed.date else None,
        "in_reply_to": parsed.in_reply_to,
        "references": parsed.references,
        "attachments": [a.__dict__ for a in parsed.attachments],
        "mailbox_id": str(mailbox.id),
        "mailbox_address": mailbox.address,
    }


def _text(parsed: ParsedEmail, reply: bool) -> str:
    text = strip_quoted(parsed.text) if reply else parsed.text
    if not text.strip():
        names = ", ".join(a.filename for a in parsed.attachments)
        text = f"(No text{f'. Attachments: {names}' if names else ''})"
    return text


def find_thread_case(session: Session, tenant_id: uuid.UUID, parsed: ParsedEmail) -> Case | None:
    """The case this email replies to, if any."""
    ids = parsed.thread_ids()
    if ids:
        stmt = select(Message).where(Message.tenant_id == tenant_id, Message.external_id.in_(ids))
        found = {m.external_id: m for m in session.scalars(stmt)}
        for message_id in ids:  # most direct parent first
            if message_id in found:
                return session.get(Case, found[message_id].case_id)
    number = case_number_in(parsed.subject)
    if number is not None:
        case = CaseRepository(session).get_by_number(tenant_id, number)
        # Only the case's own customer can reply into it by subject token.
        if case is not None and case.customer.email.lower() == parsed.from_address:
            return case
    return None


def ingest_message(
    session: Session, mailbox: Mailbox, fetched: FetchedMessage, uid_validity: int
) -> str:
    """Turn one fetched email into a case or a reply. Commits. Returns what happened."""
    from app.services.cases import CaseService  # cases imports this module's helpers

    parsed = parse_email(raw=fetched.raw, fallback_id=f"{mailbox.id}:{uid_validity}:{fetched.uid}")
    if parsed.from_address in ("", mailbox.address):
        return "skipped: sent by this inbox"
    if parsed.automatic:
        return f"skipped: automatic ({parsed.automatic})"
    # Date headers have whole seconds and senders' clocks drift: allow a little slack.
    if parsed.date is not None and parsed.date < _aware(mailbox.import_since) - CLOCK_SLACK:
        return "skipped: older than the import start"
    exists = select(Message.id).where(
        Message.tenant_id == mailbox.tenant_id, Message.external_id == parsed.message_id
    )
    if session.scalars(exists).first() is not None:
        return "skipped: already imported"

    service = CaseService(session)
    case = find_thread_case(session, mailbox.tenant_id, parsed)
    inbound = InboundEmail(parsed.message_id, _meta(parsed, mailbox), mailbox.id)
    if case is not None and CaseStatus(case.status) is not CaseStatus.CLOSED:
        service.add_message(
            mailbox.tenant_id,
            case.case_number,
            MessageCreate(kind="customer_reply", body=_text(parsed, reply=True)),
            inbound=inbound,
        )
        return f"reply on case {case.case_number}"

    attributes: dict[str, Any] = {"subject": parsed.subject}
    if case is not None:
        attributes["relatedCase"] = case.case_number
    created = service.create_case(
        mailbox.tenant_id,
        CaseCreate(
            channel="email",
            customer=CustomerIn(email=parsed.from_address, display_name=parsed.from_name),
            category=CategoryIn.model_validate(mailbox.default_category)
            if mailbox.default_category
            else None,
            message=_text(parsed, reply=case is not None),
            attributes=attributes,
        ),
        inbound=inbound,
        category_source="inbox",
    )
    return f"new case {created.case_number}"


@dataclass
class PollSummary:
    fetched: int
    outcomes: list[str]


def poll_mailbox(
    session_factory: sessionmaker[Session], transport: MailTransport, mailbox_id: uuid.UUID
) -> PollSummary:
    """Fetch new emails for one inbox and import them. Errors are recorded on the
    inbox (shown in the Operations Portal); the next scheduled poll retries."""
    with session_factory() as session:
        mailbox = session.get(Mailbox, mailbox_id)
        if mailbox is None or not mailbox.is_active:
            return PollSummary(0, [])
        mailbox.last_checked_at = utcnow()
        session.commit()
        try:
            account = account_for(mailbox)
        except Exception as exc:  # noqa: BLE001 - e.g. the encryption key changed
            mailbox.last_error = f"The stored password can't be read: re-enter it. ({exc})"
            session.commit()
            return PollSummary(0, [])
        state = (
            mailbox.uid_validity,
            mailbox.last_uid,
            _aware(mailbox.import_since),
            mailbox.mark_as_read,
        )

    try:  # no database session held while talking to the mail server
        result = transport.fetch(
            account,
            uid_validity=state[0],
            after_uid=state[1],
            since=state[2],
            limit=FETCH_BATCH,
            mark_as_read=state[3],
        )
    except MailError as exc:
        with session_factory() as session:
            mailbox = session.get(Mailbox, mailbox_id)
            if mailbox is not None:
                mailbox.last_error = str(exc)
                session.commit()
        return PollSummary(0, [])

    outcomes: list[str] = []
    for fetched in result.messages:
        with session_factory() as session:
            mailbox = session.get(Mailbox, mailbox_id)
            assert mailbox is not None
            try:
                outcome = ingest_message(session, mailbox, fetched, result.uid_validity)
            except IntegrityError:  # imported concurrently by another worker
                session.rollback()
                outcome = "skipped: already imported"
            mailbox = session.get(Mailbox, mailbox_id)
            assert mailbox is not None
            mailbox.uid_validity = result.uid_validity
            mailbox.last_uid = max(mailbox.last_uid or 0, fetched.uid)
            if outcome.startswith(("new case", "reply on")):
                mailbox.imported_total += 1
            session.commit()
            outcomes.append(outcome)

    with session_factory() as session:
        mailbox = session.get(Mailbox, mailbox_id)
        if mailbox is not None:
            mailbox.uid_validity = result.uid_validity
            mailbox.last_success_at = utcnow()
            mailbox.last_error = None
            session.commit()
    return PollSummary(len(result.messages), outcomes)


# ----- sending ---------------------------------------------------------------------------


def outbound_email(
    session: Session, case: Case, mailbox: Mailbox, body: str
) -> tuple[str, dict[str, Any]]:
    """Message-ID and email details for an agent reply on an email case (not sent yet)."""
    thread = session.scalars(
        select(Message)
        .where(Message.case_id == case.id, Message.external_id.is_not(None))
        .order_by(Message.created_at)
    ).all()
    inbound = [m for m in thread if m.direction == "inbound"]
    parent = inbound[-1] if inbound else (thread[-1] if thread else None)
    domain = mailbox.address.split("@")[-1]
    message_id = make_msgid(domain=domain)
    subject = case.attributes.get("subject") or (parent.email.get("subject") if parent else None)
    return message_id, {
        "subject": reply_subject(str(subject or "Your request"), case.case_number),
        "from": mailbox.address,
        "from_name": mailbox.display_name,
        "to": [case.customer.email],
        "in_reply_to": parent.external_id if parent else None,
        "references": [m.external_id for m in thread if m.external_id][-20:],
        "mailbox_id": str(mailbox.id),
        "mailbox_address": mailbox.address,
        "delivery": {"status": "queued", "attempts": 0, "error": None, "sent_at": None},
    }


def build_message(message: Message, mailbox: Mailbox, tenant_name: str) -> EmailMessage:
    meta = message.email
    email = EmailMessage()
    email["From"] = formataddr((mailbox.display_name or tenant_name, mailbox.address))
    email["To"] = ", ".join(meta["to"])
    email["Subject"] = meta["subject"]
    email["Message-ID"] = message.external_id
    email["Date"] = format_datetime(utcnow())
    if meta.get("in_reply_to"):
        email["In-Reply-To"] = meta["in_reply_to"]
    if meta.get("references"):
        email["References"] = " ".join(meta["references"])
    email.set_content(message.body)
    return email


def send_email_job(
    session_factory: sessionmaker[Session], transport: MailTransport, job_id: uuid.UUID
) -> None:
    """Worker handler for `send_email`. Raises MailError so the job is retried."""
    with session_factory() as session:
        job = session.get(Job, job_id)
        message = session.get(Message, uuid.UUID(job.payload["message_id"])) if job else None
        if job is None or message is None:
            return
        delivery = dict(message.email.get("delivery") or {})
        if delivery.get("status") == "sent":  # already sent: never send twice
            job.status = "done"
            session.commit()
            return
        mailbox = session.get(Mailbox, uuid.UUID(message.email["mailbox_id"]))
        tenant = session.get(Tenant, message.tenant_id)
        if mailbox is None or tenant is None:
            _set_delivery(session, message, status="failed", error="The inbox was removed.")
            job.status = "done"
            session.commit()
            return
        account = account_for(mailbox)
        email = build_message(message, mailbox, tenant.name)
        attempt = job.attempts
        message_id = message.id

    try:
        transport.send(account, email)
    except MailError as exc:
        with session_factory() as session:
            message = session.get(Message, message_id)
            if message is not None:
                _set_delivery(session, message, status="retrying", error=str(exc), attempts=attempt)
                session.commit()
        raise

    with session_factory() as session:
        message = session.get(Message, message_id)
        job = session.get(Job, job_id)
        assert message is not None and job is not None
        _set_delivery(session, message, status="sent", error=None, attempts=attempt, sent=True)
        session.add(
            CaseEvent(
                tenant_id=message.tenant_id,
                case_id=message.case_id,
                event_type="email.sent",
                actor_type="system",
                data={"messageId": str(message.id), "to": message.email.get("to")},
            )
        )
        job.status = "done"
        session.commit()


def send_failed(session: Session, job: Job, error: str) -> None:
    """The last attempt failed: show it on the message and in the case history."""
    message = session.get(Message, uuid.UUID(job.payload["message_id"]))
    if message is None:
        return
    _set_delivery(session, message, status="failed", error=error.strip().splitlines()[-1][:300])
    session.add(
        CaseEvent(
            tenant_id=message.tenant_id,
            case_id=message.case_id,
            event_type="email.failed",
            actor_type="system",
            reason=message.email["delivery"]["error"],
            data={"messageId": str(message.id)},
        )
    )


def _set_delivery(
    session: Session,
    message: Message,
    *,
    status: str,
    error: str | None,
    attempts: int | None = None,
    sent: bool = False,
) -> None:
    delivery = dict(message.email.get("delivery") or {})
    delivery.update(status=status, error=error)
    if attempts is not None:
        delivery["attempts"] = attempts
    if sent:
        delivery["sent_at"] = utcnow().isoformat()
    message.email = {**message.email, "delivery": delivery}


def retry_send(
    session: Session, tenant_id: uuid.UUID, case: Case, message_id: uuid.UUID
) -> Message:
    """Queue a failed email again (e.g. after fixing the inbox password)."""
    message = session.get(Message, message_id)
    if message is None or message.tenant_id != tenant_id or message.case_id != case.id:
        raise NotFoundError(f"Message {message_id} not found.")
    status = (message.email.get("delivery") or {}).get("status")
    if status != "failed":
        raise ConflictError(
            f"Only failed emails can be retried (this one is {status or 'not an email'})."
        )
    _set_delivery(session, message, status="queued", error=None)
    session.add(
        Job(
            tenant_id=tenant_id,
            kind="send_email",
            case_id=case.id,
            payload={"message_id": str(message.id)},
        )
    )
    session.commit()
    return message
