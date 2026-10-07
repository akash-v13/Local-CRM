"""Automatic replies: a new case is answered after a delay, unless a person steps in.

    routed to a queue with auto_send ──► "auto_reply" job (prepare)
        checks pass ──► draft (standard reply or AI) ──► case "With AI", sends at T
        checks fail ──► held: stays in the queue for a person, with the reason
    at T ──► "auto_reply" job (send) ──► checks again ──► sent, case Solved

Two ways to write the reply (queue setting `auto_send_mode`):
- **template**: the queue's standard reply with the case's details filled in
  ({{customer.first_name}}, {{case.order}}, {{compensation.sentence}}…). No AI cost.
  Rendered again at send time, so it quotes the final voucher code.
- **ai**: written by the AI from the business's layered prompt templates, exactly
  like "Draft with AI" (services/replies.py). A draft the checks flag is held.

The delay (`auto_send_delay_minutes`, 6 hours by default) makes replies arrive like a
person's and leaves time to step in: the case page shows when it will go out, with
**Send now** and **Cancel**. Anything a person should see first holds it:
- compensation waiting for approval, or its payout failed;
- a complaint no compensation rule matched;
- a value the reader wasn't sure about (an agent must confirm it);
- an AI draft with warnings; a standard reply using data the case doesn't have.
While a refund or code is still being issued, the reply waits (so it can quote it).
At send time the case is checked again: if the customer wrote again or someone took
the case, the reply is not sent.

State lives on the case as `decisions.auto_reply`:
`{status: scheduled|held|sent|cancelled, mode, draft_id, scheduled_at, send_at, reason}`.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.ai.drafter import DraftWriter
from app.domain.errors import AIDisabledError, AIDraftFailedError, ConflictError, NotFoundError
from app.domain.jsonpath import extract
from app.domain.lifecycle import CaseStatus
from app.domain.templates import PLACEHOLDER
from app.models import Case, CaseEvent, Job, Message, Queue, Tenant
from app.models.base import utcnow
from app.repositories import CaseRepository
from app.schemas import MessageCreate, QueueSettings
from app.services.routing import enrichment_data

AUTHOR = "auto-reply"  # message author_id / event actor for automatic replies
WAIT_FOR_PAYOUT = timedelta(minutes=2)  # check again this soon while a payout is in flight
MAX_PAYOUT_WAITS = 30  # about an hour, then hold for a person
PAYOUT_PENDING = ("queued", "processing", "retrying")


class MissingValue(Exception):
    def __init__(self, path: str) -> None:
        super().__init__(path)
        self.path = path


def _as_utc(value: datetime) -> datetime:
    """SQLite (tests) returns naive datetimes; treat them as UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


# ----- the standard reply ----------------------------------------------------------------


def reply_context(case: Case, business_name: str) -> dict[str, Any]:
    """What a standard reply's {{placeholders}} can use. Always-present keys get friendly
    fallbacks, so the default template works on every case."""
    name = (case.customer.display_name or "").strip()
    order = case.attributes.get("orderNumber")
    decision = case.decisions.get("compensation") or {}
    approved = decision.get("status") == "approved" and decision.get("label")
    return {
        "customer": {
            "name": name or "there",
            "first_name": name.split()[0] if name else "there",
            "email": case.customer.email,
        },
        "case": {
            "number": case.case_number,
            "order": f"order {order}" if order else "your order",
            "order_number": order,
            "category": (case.category.get("effective") or {}).get("category"),
            "subcategory": (case.category.get("effective") or {}).get("subcategory"),
            "attributes": dict(case.attributes),
        },
        "compensation": {
            "label": decision.get("label") if approved else None,
            "sentence": f"Here's what we've done: {decision['label']}." if approved else "",
        },
        "business": {"name": business_name},
        "enrichment": enrichment_data(case),
    }


def render_reply(template: str, context: dict[str, Any]) -> str:
    """Fill {{placeholders}}. An empty value is fine; a path the case doesn't have isn't."""

    def substitute(match: Any) -> str:
        found, value = extract(context, match.group(1))
        if not found or value is None:
            raise MissingValue(match.group(1))
        return str(value)

    text = PLACEHOLDER.sub(substitute, template)
    # A blank {{compensation.sentence}} can leave a stray space before a line break.
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


# ----- checks -----------------------------------------------------------------------------


def hold_reason(case: Case) -> str | None:
    """Why a person should look first, or None."""
    decision = case.decisions.get("compensation") or {}
    status = decision.get("status")
    if status == "pending_approval":
        return "Compensation is waiting for approval."
    if status == "no_match" and (case.category.get("effective") or {}).get("type") == "Complaint":
        return "No compensation rule matched this complaint."
    payout = decision.get("payout") or {}
    if payout.get("status") == "failed":
        return f"The payout failed: {payout.get('error') or 'see the case'}."
    unsure = [
        f.get("label") or f.get("key")
        for f in (case.extraction or {}).get("fields", [])
        if f.get("status") == "needs_review"
    ]
    if unsure:
        return f"An agent needs to confirm: {', '.join(unsure)}."
    return None


def payout_in_flight(case: Case) -> bool:
    payout = (case.decisions.get("compensation") or {}).get("payout") or {}
    return payout.get("status") in PAYOUT_PENDING


def _record(case: Case, **values: Any) -> None:
    current = dict(case.decisions.get("auto_reply") or {})
    case.decisions = {**case.decisions, "auto_reply": {**current, **values}}


def _event(session: Session, case: Case, kind: str, reason: str | None, **data: Any) -> None:
    session.add(
        CaseEvent(
            tenant_id=case.tenant_id,
            case_id=case.id,
            event_type=f"auto_reply.{kind}",
            actor_type="ai",
            actor_id=AUTHOR,
            reason=reason,
            data=data,
        )
    )


def settings_for(case: Case) -> QueueSettings | None:
    queue: Queue | None = case.queue
    if queue is None:
        return None
    settings = QueueSettings.model_validate(queue.settings or {})
    return settings if settings.auto_send else None


# ----- scheduling (called when a new case is routed) ---------------------------------------


def queue_auto_reply(session: Session, case: Case) -> None:
    """Add the prepare job when the case's queue answers automatically. Does NOT commit."""
    if settings_for(case) is None or case.decisions.get("auto_reply"):
        return
    _record(case, status="preparing", scheduled_at=None)
    session.add(
        Job(
            tenant_id=case.tenant_id,
            kind="auto_reply",
            case_id=case.id,
            payload={"step": "prepare"},
        )
    )


def _next_job(session: Session, case: Case, step: str, run_after: datetime, **payload: Any) -> None:
    session.add(
        Job(
            tenant_id=case.tenant_id,
            kind="auto_reply",
            case_id=case.id,
            payload={"step": step, **payload},
            run_after=run_after,
        )
    )


def _hold(session: Session, case: Case, reason: str) -> None:
    from app.services.cases import CaseService  # cases imports this module

    if CaseStatus(case.status) is CaseStatus.ASSIGNED_AI:
        CaseService(session).apply_transition(
            case, CaseStatus.QUEUED, "ai", AUTHOR, "Automatic reply held for a person"
        )
    _record(case, status="held", reason=reason)
    _event(session, case, "held", reason)


def auto_reply_job(
    session_factory: sessionmaker[Session], writer: DraftWriter | None, job_id: uuid.UUID
) -> None:
    """Worker handler for `auto_reply` jobs (payload step: prepare | send)."""
    with session_factory() as session:
        job = session.get(Job, job_id)
        case = session.get(Case, job.case_id) if job and job.case_id else None
        if job is None or case is None:
            return
        job.status = "done"
        if job.payload.get("step") == "send":
            _send(session, case, job)
        else:
            _prepare(session, case, job, writer)
        case.updated_at = utcnow()
        session.commit()


def _prepare(session: Session, case: Case, job: Job, writer: DraftWriter | None) -> None:
    from app.services.cases import CaseService
    from app.services.replies import DraftService

    settings = settings_for(case)
    state = case.decisions.get("auto_reply") or {}
    if settings is None or state.get("status") not in ("preparing", None):
        return
    if CaseStatus(case.status) is not CaseStatus.QUEUED:
        _record(case, status="cancelled", reason=f"The case is {case.status}.")
        return
    if payout_in_flight(case):  # wait so the reply can say what was issued
        waits = int(job.payload.get("waits", 0)) + 1
        if waits > MAX_PAYOUT_WAITS:
            _hold(session, case, "The payout is taking too long.")
        else:
            _next_job(session, case, "prepare", utcnow() + WAIT_FOR_PAYOUT, waits=waits)
        return
    reason = hold_reason(case)
    if reason:
        _hold(session, case, reason)
        return

    tenant = session.get(Tenant, case.tenant_id)
    assert tenant is not None
    if settings.auto_send_mode == "template":
        try:
            body = render_reply(settings.auto_send_template, reply_context(case, tenant.name))
        except MissingValue as exc:
            _hold(
                session,
                case,
                f"The standard reply uses {{{{{exc.path}}}}}, which this case doesn't have.",
            )
            return
        draft = Message(
            tenant_id=case.tenant_id,
            case_id=case.id,
            direction="internal",
            channel="draft",
            author_type="system",
            author_id=AUTHOR,
            visibility="draft",
            body=body,
            ai={"auto_reply": "template"},
        )
        session.add(draft)
        session.flush()
    else:
        if writer is None:
            _hold(session, case, "AI drafting isn't set up (no Anthropic API key).")
            return
        # The draft service commits before calling the model (no transaction held while
        # waiting); `case` is then re-read on access, so a person's changes show up.
        try:
            draft = DraftService(session).draft_for_case(
                case.tenant_id, case.case_number, writer, None
            )
        except (AIDisabledError, AIDraftFailedError) as exc:
            _hold(session, case, f"The AI couldn't draft a reply: {exc}")
            return
        concerns = [str(w) for w in draft.ai.get("warnings") or []]
        if draft.ai.get("needs_attention"):
            concerns.insert(0, str(draft.ai.get("attention_reason") or "the AI flagged it"))
        if concerns:
            _hold(session, case, "The AI draft needs a look: " + "; ".join(concerns))
            return
        if CaseStatus(case.status) is not CaseStatus.QUEUED:  # someone took it while drafting
            _record(case, status="cancelled", reason="Someone picked the case up.")
            return

    now = utcnow()
    send_at = now + timedelta(minutes=settings.auto_send_delay_minutes)
    CaseService(session).apply_transition(
        case, CaseStatus.ASSIGNED_AI, "ai", AUTHOR, "Automatic reply scheduled"
    )
    _record(
        case,
        status="scheduled",
        mode=settings.auto_send_mode,
        draft_id=str(draft.id),
        scheduled_at=now.isoformat(),
        send_at=send_at.isoformat(),
        reason=None,
    )
    _event(
        session, case, "scheduled", None, sendAt=send_at.isoformat(), mode=settings.auto_send_mode
    )
    _next_job(session, case, "send", send_at, due=send_at.isoformat())


def _customer_wrote_again(session: Session, case: Case, since: datetime) -> bool:
    stmt = select(Message.created_at).where(
        Message.case_id == case.id, Message.author_type == "customer"
    )
    return any(_as_utc(t) > since for t in session.scalars(stmt))


def _send(session: Session, case: Case, job: Job) -> None:
    from app.services.cases import CaseService

    state = case.decisions.get("auto_reply") or {}
    if state.get("status") != "scheduled":
        return  # cancelled, sent or held meanwhile
    if job.payload.get("due") != state.get("send_at"):
        return  # an older send job, superseded by Send now
    if CaseStatus(case.status) is not CaseStatus.ASSIGNED_AI:
        _record(case, status="cancelled", reason=f"Someone took the case ({case.status}).")
        _event(session, case, "cancelled", "Someone took the case.")
        return
    if _customer_wrote_again(session, case, _as_utc(datetime.fromisoformat(state["scheduled_at"]))):
        _hold(session, case, "The customer wrote again.")
        return
    if payout_in_flight(case):
        waits = int(job.payload.get("waits", 0)) + 1
        if waits > MAX_PAYOUT_WAITS:
            _hold(session, case, "The payout is taking too long.")
        else:
            _next_job(
                session,
                case,
                "send",
                utcnow() + WAIT_FOR_PAYOUT,
                waits=waits,
                due=state.get("send_at"),
            )
        return
    reason = hold_reason(case)
    if reason:
        _hold(session, case, reason)
        return
    draft = session.get(Message, uuid.UUID(state["draft_id"]))
    if draft is None or draft.case_id != case.id:
        _hold(session, case, "The drafted reply is gone.")
        return
    body = draft.body
    if state.get("mode") == "template":  # again, so it quotes the final voucher code
        settings = settings_for(case)
        tenant = session.get(Tenant, case.tenant_id)
        if settings is not None and tenant is not None:
            try:
                body = render_reply(settings.auto_send_template, reply_context(case, tenant.name))
            except MissingValue:
                pass  # keep the reply drafted at prepare time
    _record(case, status="sent", sent_at=utcnow().isoformat())
    _event(session, case, "sent", None)
    CaseService(session).add_message(
        case.tenant_id,
        case.case_number,
        MessageCreate(
            kind="agent_reply",
            body=body,
            author_id=AUTHOR,
            then_status=CaseStatus.SOLVED,
            from_draft_id=draft.id,
        ),
        author_type="ai",
    )


# ----- a person stepping in --------------------------------------------------------------


class AutoReplyService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.cases = CaseRepository(session)

    def _scheduled(self, tenant_id: uuid.UUID, case_number: int) -> Case:
        case = self.cases.get_by_number(tenant_id, case_number)
        if case is None:
            raise NotFoundError(f"Case {case_number} not found.")
        if (case.decisions.get("auto_reply") or {}).get("status") != "scheduled":
            raise ConflictError("No automatic reply is waiting to be sent on this case.")
        return case

    def send_now(self, tenant_id: uuid.UUID, case_number: int, actor_id: str) -> Case:
        case = self._scheduled(tenant_id, case_number)
        now = utcnow().isoformat()
        _record(case, send_at=now, released_by=actor_id)
        _next_job(self.session, case, "send", utcnow(), due=now)
        _event(self.session, case, "released", f"Sent early by {actor_id}")
        case.updated_at = utcnow()
        self.session.commit()
        return case

    def cancel(self, tenant_id: uuid.UUID, case_number: int, actor_id: str) -> Case:
        """Stop the reply; the person takes the case (the draft stays, to edit and send)."""
        from app.services.cases import CaseService

        case = self._scheduled(tenant_id, case_number)
        CaseService(self.session).apply_transition(
            case, CaseStatus.ASSIGNED_AGENT, "human", actor_id, "Automatic reply cancelled"
        )
        _record(case, status="cancelled", reason=f"Cancelled by {actor_id}.")
        self.session.add(
            CaseEvent(
                tenant_id=case.tenant_id,
                case_id=case.id,
                event_type="auto_reply.cancelled",
                actor_type="human",
                actor_id=actor_id,
                reason="Cancelled the automatic reply",
            )
        )
        case.updated_at = utcnow()
        self.session.commit()
        return case

    def preview(self, tenant_id: uuid.UUID, case_number: int, template: str) -> str:
        """A standard reply rendered for a real case (for the queue editor)."""
        case = self.cases.get_by_number(tenant_id, case_number)
        tenant = self.session.get(Tenant, tenant_id)
        if case is None or tenant is None:
            raise NotFoundError(f"Case {case_number} not found.")
        try:
            return render_reply(template, reply_context(case, tenant.name))
        except MissingValue as exc:
            raise ConflictError(f"This case has no value for {{{{{exc.path}}}}}.") from exc
