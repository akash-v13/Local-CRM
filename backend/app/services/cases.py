"""Case operations: intake, routing, status changes and correspondence."""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from app.domain.errors import CaseClosedError, ConflictError, NotFoundError, RoutingError
from app.domain.ids import next_case_number
from app.domain.lifecycle import CaseStatus, ensure_transition_allowed
from app.domain.routing import describe_condition, route
from app.models import Case, CaseEvent, Customer, Job, Mailbox, Message, Queue
from app.models.base import utcnow
from app.repositories import (
    CaseEventRepository,
    CaseRepository,
    ConnectorRepository,
    CustomerRepository,
    JobRepository,
    MessageRepository,
    QueueRepository,
    TenantRepository,
)
from app.schemas import (
    ActorType,
    CaseCreate,
    EnrichRequest,
    MessageCreate,
    RerouteRequest,
    RouteRequest,
    TransitionRequest,
)
from app.services.compensation import CompensationService
from app.services.email import InboundEmail, outbound_email
from app.services.reading import queue_reading, settings_of, should_read
from app.services.routing import case_context, to_candidate

# How many times to retry if two servers pick the same case number (same microsecond).
CASE_NUMBER_ATTEMPTS = 5


class CaseService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.customers = CustomerRepository(session)
        self.cases = CaseRepository(session)
        self.queues = QueueRepository(session)
        self.connectors = ConnectorRepository(session)
        self.jobs = JobRepository(session)
        self.messages = MessageRepository(session)
        self.events = CaseEventRepository(session)

    # ----- intake -------------------------------------------------------------------------

    def create_case(
        self,
        tenant_id: uuid.UUID,
        data: CaseCreate,
        *,
        inbound: InboundEmail | None = None,
        category_source: str = "customer",
    ) -> Case:
        """Intake: create the case and its first message, then enrich or route it.

        All in one transaction. The customer is matched by email within the
        tenant, or created.

        - If the business reads messages for this channel (app/services/reading.py), a
          `read_case` job is queued first; it fills in fields/category, then continues below.
        - If the tenant has active connectors, an `enrich_case` job is queued and
          the case stays in Intake; the worker enriches it and then routes it,
          so routing rules can use enriched data (order value, days late, ...).
        - Otherwise it's routed right away: Intake → Queued if a queue matches,
          or it stays in Intake with a `case.unrouted` event.

        `inbound` (from the email importer) attaches the email's Message-ID and
        details to the first message, and the inbox to the case. `category_source`
        says where `data.category` came from ("customer", or "inbox" for an inbox's
        default, which reading may replace).
        """
        if self.tenants.get(tenant_id) is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")

        customer = self.customers.find_by_email(tenant_id, data.customer.email)
        if customer is None:
            customer = Customer(
                tenant_id=tenant_id,
                email=data.customer.email,
                display_name=data.customer.display_name,
                tier=data.customer.tier,
            )
            self.customers.add(customer)
            self.session.flush()  # assigns customer.id so the case can reference it

        selected = data.category.model_dump() if data.category else None
        case = Case(
            tenant_id=tenant_id,
            customer=customer,
            status=CaseStatus.INTAKE.value,
            channel=data.channel,
            language=data.language,
            # Both are kept (Idea 8): `effective` may later be corrected by AI or an agent.
            category={
                "customerSelected": selected if category_source == "customer" else None,
                "effective": selected,
                "source": category_source,
            },
            attributes=data.attributes,
            mailbox_id=inbound.mailbox_id if inbound else None,
        )
        self._insert_with_case_number(case)

        self.messages.add(
            Message(
                tenant_id=tenant_id,
                case_id=case.id,
                direction="inbound",
                channel=data.channel,
                author_type="customer",
                author_id=str(customer.id),
                visibility="public",
                body=data.message,
                external_id=inbound.external_id if inbound else None,
                email=inbound.meta if inbound else {},
            )
        )
        self.events.add(
            CaseEvent(
                tenant_id=tenant_id,
                case_id=case.id,
                event_type="case.created",
                to_status=CaseStatus.INTAKE.value,
                actor_type="system",
            )
        )
        tenant = self.tenants.get(tenant_id)
        if tenant is not None and should_read(settings_of(tenant), case):
            queue_reading(self.session, case)  # the read_case job continues intake afterwards
        else:
            self.continue_intake(case, [data.message])
        self.session.commit()
        return case

    def continue_intake(self, case: Case, customer_texts: list[str] | None = None) -> None:
        """The next intake step: enrichment if the business has connectors (or a connected
        Shopify store), else routing. Does NOT commit."""
        tenant = self.tenants.get(case.tenant_id)
        shopify_on = tenant is not None and bool((tenant.shopify_settings or {}).get("enabled"))
        if shopify_on or self.connectors.has_active(case.tenant_id):
            self._queue_enrichment(case, "system", None)
        else:
            texts = customer_texts or self.messages.customer_texts(case.tenant_id, case.id)
            self.apply_routing(case, texts, "system", None)

    def _queue_enrichment(self, case: Case, actor_type: ActorType, actor_id: str | None) -> None:
        """Add an enrich_case job (committed with the caller's transaction)."""
        self.jobs.add(Job(tenant_id=case.tenant_id, kind="enrich_case", case_id=case.id))
        self.events.add(
            CaseEvent(
                tenant_id=case.tenant_id,
                case_id=case.id,
                event_type="enrichment.queued",
                actor_type=actor_type,
                actor_id=actor_id,
            )
        )

    def _insert_with_case_number(self, case: Case) -> None:
        """Insert the case with a fresh case number, retrying on a cross-server collision.

        Each attempt runs in a SAVEPOINT, so a duplicate-number failure only
        undoes this insert, not the customer created earlier in the transaction.
        """
        for attempt in range(1, CASE_NUMBER_ATTEMPTS + 1):
            case.case_number = next_case_number()
            try:
                with self.session.begin_nested():
                    self.cases.add(case)
                    self.session.flush()  # also assigns case.id
                return
            except IntegrityError as exc:
                if "case_number" not in str(exc.orig) or attempt == CASE_NUMBER_ATTEMPTS:
                    raise

    # ----- reads --------------------------------------------------------------------------

    def get_case(self, tenant_id: uuid.UUID, case_number: int) -> Case:
        case = self.cases.get_by_number(tenant_id, case_number)
        if case is None:
            raise NotFoundError(f"Case {case_number} not found.")
        return case

    def list_cases(
        self,
        tenant_id: uuid.UUID,
        status: CaseStatus | None,
        queue_id: uuid.UUID | None,
        unrouted: bool,
        limit: int,
        offset: int,
    ) -> Sequence[Case]:
        return self.cases.list(
            tenant_id,
            status=status,
            queue_id=queue_id,
            unrouted=unrouted,
            limit=limit,
            offset=offset,
        )

    def list_messages(self, tenant_id: uuid.UUID, case_number: int) -> Sequence[Message]:
        case = self.get_case(tenant_id, case_number)
        return self.messages.list_for_case(tenant_id, case.id)

    def list_events(self, tenant_id: uuid.UUID, case_number: int) -> Sequence[CaseEvent]:
        case = self.get_case(tenant_id, case_number)  # 404 if the case isn't this tenant's
        return self.events.list_for_case(tenant_id, case.id)

    # ----- routing ------------------------------------------------------------------------

    def enrich(self, tenant_id: uuid.UUID, case_number: int, req: EnrichRequest) -> Case:
        """Run the connectors again for this case (e.g. after fixing a connector).

        From EnrichmentFailed the case goes back to Intake and is routed once
        enrichment succeeds. Other open cases just get their data refreshed.
        """
        case = self.get_case(tenant_id, case_number)
        status = CaseStatus(case.status)
        if status is CaseStatus.CLOSED:
            raise RoutingError("Closed cases can't be enriched again.")
        if self.jobs.pending_for_case(case.id) is not None:
            raise ConflictError("Enrichment is already queued or running for this case.")
        if status is CaseStatus.ENRICHMENT_FAILED:
            self.apply_transition(
                case, CaseStatus.INTAKE, "human", req.actor_id, "Retrying enrichment"
            )
        self._queue_enrichment(case, "human", req.actor_id)
        case.updated_at = utcnow()
        self.commit_case(case)
        return case

    def route_case(self, tenant_id: uuid.UUID, case_number: int, req: RouteRequest) -> Case:
        """Run queue matching again, e.g. after queues were added or changed.

        Only for cases still waiting for a handler (Intake or Queued), and not
        for cases an agent pinned to a queue with a manual reroute.
        """
        case = self.get_case(tenant_id, case_number)
        status = CaseStatus(case.status)
        if status not in (CaseStatus.INTAKE, CaseStatus.QUEUED):
            raise RoutingError(
                f"Only Intake or Queued cases can be routed automatically; this case is {status}."
            )
        if case.assignment_pinned:
            raise RoutingError(
                "An agent pinned this case to its queue. Use reroute to move it manually."
            )
        texts = self.messages.customer_texts(tenant_id, case.id)
        self.apply_routing(case, texts, req.actor_type, req.actor_id)
        case.updated_at = utcnow()
        self.commit_case(case)
        return case

    def reroute(self, tenant_id: uuid.UUID, case_number: int, req: RerouteRequest) -> Case:
        """Manually move a case to a specific queue (Idea 8).

        The case goes back to Queued (if the lifecycle allows it) and is
        **pinned**: automatic routing won't move it again.
        """
        case = self.get_case(tenant_id, case_number)
        queue = self.queues.get(tenant_id, req.queue_id)
        if queue is None:
            raise NotFoundError(f"Queue {req.queue_id} not found.")
        if not queue.is_active:
            raise RoutingError(f"Queue '{queue.name}' is inactive.")

        previous: Queue | None = case.queue
        reason = req.reason or f"Rerouted to {queue.name}"
        if CaseStatus(case.status) is not CaseStatus.QUEUED:
            self.apply_transition(case, CaseStatus.QUEUED, "human", req.actor_id, reason)

        case.queue = queue
        case.assignment_pinned = True
        self.events.add(
            CaseEvent(
                tenant_id=tenant_id,
                case_id=case.id,
                event_type="case.rerouted",
                actor_type="human",
                actor_id=req.actor_id,
                reason=req.reason,
                data={
                    "fromQueueId": str(previous.id) if previous else None,
                    "fromQueueName": previous.name if previous else None,
                    "toQueueId": str(queue.id),
                    "toQueueName": queue.name,
                },
            )
        )
        case.updated_at = utcnow()
        self.commit_case(case)
        return case

    def apply_routing(
        self, case: Case, customer_texts: list[str], actor_type: ActorType, actor_id: str | None
    ) -> None:
        """Match the case against active queues and assign the winner. Does NOT commit.

        Records *why* in the event (which conditions matched), so agents and
        managers can see the reasoning in the case history.
        """
        queues = {q.id: q for q in self.queues.list(case.tenant_id, active_only=True)}
        result = route(
            [to_candidate(q) for q in queues.values()], case_context(case, customer_texts)
        )

        if result.winner is None or result.winner.id is None:
            self.events.add(
                CaseEvent(
                    tenant_id=case.tenant_id,
                    case_id=case.id,
                    event_type="case.unrouted",
                    actor_type=actor_type,
                    actor_id=actor_id,
                    reason="No active queue matched this case.",
                    data={"queuesChecked": len(queues)},
                )
            )
            return

        winner = queues[result.winner.id]
        evaluation = next(e for e in result.evaluations if e.queue is result.winner)
        previous_id = case.queue_id
        case.queue = winner
        self.events.add(
            CaseEvent(
                tenant_id=case.tenant_id,
                case_id=case.id,
                event_type="case.routed",
                actor_type=actor_type,
                actor_id=actor_id,
                data={
                    "queueId": str(winner.id),
                    "queueName": winner.name,
                    "priority": winner.priority,
                    "previousQueueId": str(previous_id) if previous_id else None,
                    "matchedConditions": [describe_condition(c) for c in evaluation.conditions],
                },
            )
        )
        if CaseStatus(case.status) is CaseStatus.INTAKE:
            self.apply_transition(
                case, CaseStatus.QUEUED, actor_type, actor_id, f"Routed to {winner.name}"
            )
        # Decide compensation once the case is routed (rules can test the queue).
        CompensationService(self.session).decide_for_case(
            case, customer_texts, actor_type, actor_id, only_if_undecided=True
        )

    # ----- status and correspondence ------------------------------------------------------

    def transition(self, tenant_id: uuid.UUID, case_number: int, req: TransitionRequest) -> Case:
        """Move a case to a new status, validated against the lifecycle, with an event."""
        case = self.get_case(tenant_id, case_number)

        if req.expected_version is not None and req.expected_version != case.version:
            raise ConflictError(
                f"Case {case_number} is at version {case.version}, "
                f"but the request expected {req.expected_version}. Reload and retry."
            )

        self.apply_transition(case, req.to_status, req.actor_type, req.actor_id, req.reason)
        self.commit_case(case)
        return case

    def add_message(
        self,
        tenant_id: uuid.UUID,
        case_number: int,
        req: MessageCreate,
        *,
        inbound: InboundEmail | None = None,
    ) -> Message:
        """Add correspondence to a case.

        - `agent_reply`: outbound, visible to the customer. On a case that came in
          by email, a `send_email` job emails it from the case's inbox (threaded
          into the customer's conversation); otherwise sending is simulated.
          Optionally moves the case to `then_status` in the same transaction.
        - `internal_note`: only visible to agents. Allowed on any case, even closed.
        - `customer_reply`: inbound. If the case was `Solved` or `WaitingOnCustomer`,
          it goes back to `Queued` (same queue) so someone looks at it again (Idea 7).
          `inbound` carries the email details when the reply came from the importer.

        Replies of either kind are rejected on a `Closed` case.
        """
        case = self.get_case(tenant_id, case_number)
        status = CaseStatus(case.status)

        if req.kind != "internal_note" and status is CaseStatus.CLOSED:
            raise CaseClosedError(
                f"Case {case_number} is closed. Replies are not accepted; open a new case instead."
            )

        if req.kind == "agent_reply":
            message = Message(
                direction="outbound", author_type="human", visibility="public", channel="email"
            )
            event_type, event_data = "message.sent", {"delivery": "simulated"}
            if req.from_draft_id is not None:
                event_data.update(self._draft_usage(case, req.from_draft_id, req.body))
        elif req.kind == "internal_note":
            message = Message(
                direction="internal", author_type="human", visibility="internal", channel="note"
            )
            event_type, event_data = "note.added", {}
        else:
            message = Message(
                direction="inbound", author_type="customer", visibility="public", channel="email"
            )
            event_type, event_data = "message.received", {}
        event_data = dict(event_data)

        message.tenant_id = tenant_id
        message.case_id = case.id
        message.author_id = str(case.customer_id) if req.kind == "customer_reply" else req.author_id
        message.body = req.body
        message.email = {}
        if inbound is not None:
            message.external_id, message.email = inbound.external_id, inbound.meta
        mailbox = self.session.get(Mailbox, case.mailbox_id) if case.mailbox_id else None
        if req.kind == "agent_reply" and mailbox is not None:
            message.external_id, message.email = outbound_email(
                self.session, case, mailbox, req.body
            )
            event_data["delivery"] = "email"
            event_data["to"] = case.customer.email
        self.messages.add(message)
        self.session.flush()  # assigns message.id
        if req.kind == "agent_reply" and mailbox is not None:
            self.jobs.add(
                Job(
                    tenant_id=tenant_id,
                    kind="send_email",
                    case_id=case.id,
                    payload={"message_id": str(message.id)},
                    max_attempts=5,
                )
            )

        actor: ActorType = "customer" if req.kind == "customer_reply" else "human"
        self.events.add(
            CaseEvent(
                tenant_id=tenant_id,
                case_id=case.id,
                event_type=event_type,
                actor_type=actor,
                actor_id=message.author_id,
                data={**event_data, "messageId": str(message.id)},
            )
        )

        if req.kind == "customer_reply" and status in (
            CaseStatus.SOLVED,
            CaseStatus.WAITING_ON_CUSTOMER,
        ):
            self.apply_transition(case, CaseStatus.QUEUED, "customer", None, "Customer replied")
        elif req.kind == "agent_reply" and req.then_status is not None:
            self.apply_transition(case, req.then_status, "human", req.author_id, None)

        case.updated_at = utcnow()  # marks the case changed, so its version is bumped
        self.commit_case(case)
        return message

    def _draft_usage(self, case: Case, draft_id: uuid.UUID, sent_body: str) -> dict[str, Any]:
        """How a sent reply relates to the AI draft it started from.

        `draftEdited` (did the agent change the draft before sending?) is the
        most useful quality signal for AI drafting: unedited drafts mean the
        template and model are doing their job.
        """
        draft = self.session.get(Message, draft_id)
        if draft is None or draft.case_id != case.id or draft.author_type != "ai":
            raise NotFoundError(f"Draft {draft_id} not found on this case.")

        def normalize(text: str) -> str:
            return " ".join(text.split())

        return {
            "fromDraftId": str(draft.id),
            "draftEdited": normalize(draft.body) != normalize(sent_body),
            "draftModel": draft.ai.get("served_by"),
            "draftTemplates": [
                f"{t.get('name')} v{t.get('version')}" for t in draft.ai.get("templates", [])
            ],
        }

    def apply_transition(
        self,
        case: Case,
        to_status: CaseStatus,
        actor_type: ActorType,
        actor_id: str | None,
        reason: str | None,
    ) -> None:
        """Validate and apply a status change plus its event. Does NOT commit.

        Also keeps the assignee in step with the status: assigning to an agent
        records who, assigning to AI records the AI, and going back to a queue
        clears the assignee.
        """
        current = CaseStatus(case.status)
        ensure_transition_allowed(current, to_status)

        case.status = to_status.value
        case.status_changed_at = utcnow()
        if to_status is CaseStatus.ASSIGNED_AGENT:
            case.assignee_type, case.assignee_id = "human", actor_id
        elif to_status is CaseStatus.ASSIGNED_AI:
            case.assignee_type, case.assignee_id = "ai", "ai_reply_agent"
        elif to_status is CaseStatus.QUEUED:
            case.assignee_type, case.assignee_id = None, None

        self.events.add(
            CaseEvent(
                tenant_id=case.tenant_id,
                case_id=case.id,
                event_type="case.status_changed",
                from_status=current.value,
                to_status=to_status.value,
                actor_type=actor_type,
                actor_id=actor_id,
                reason=reason,
            )
        )

    def commit_case(self, case: Case) -> None:
        """Commit, turning a lost optimistic-locking race into a ConflictError."""
        try:
            self.session.commit()
        except StaleDataError as exc:  # someone else saved the case after we loaded it
            self.session.rollback()
            raise ConflictError(
                f"Case {case.case_number} was changed by someone else. Retry."
            ) from exc
