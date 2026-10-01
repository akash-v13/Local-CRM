"""Queue management and routing preview (Operations Portal)."""

import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.domain.errors import NotFoundError
from app.domain.routing import (
    ENRICHMENT_PREFIX,
    FIELDS,
    LIST_OPERATORS,
    OPERATORS,
    QueueCandidate,
    describe_condition,
    route,
)
from app.domain.taxonomy import DEFAULT_TAXONOMY
from app.models import Queue
from app.models.base import utcnow
from app.repositories import (
    CaseRepository,
    ConnectorRepository,
    CustomerRepository,
    MessageRepository,
    QueueRepository,
    TenantRepository,
)
from app.schemas import (
    ConditionResultRead,
    QueueCreate,
    QueueEvaluationRead,
    QueueUpdate,
    RoutingField,
    RoutingFields,
    RoutingOperator,
    RoutingPreview,
    RoutingPreviewRequest,
)
from app.services.routing import case_context, to_candidate

CHANNELS = ["webform", "email", "chat", "api"]


class QueueService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.queues = QueueRepository(session)
        self.cases = CaseRepository(session)
        self.customers = CustomerRepository(session)
        self.connectors = ConnectorRepository(session)
        self.messages = MessageRepository(session)

    def _require_tenant(self, tenant_id: uuid.UUID) -> None:
        if self.tenants.get(tenant_id) is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")

    def list(self, tenant_id: uuid.UUID) -> Sequence[Queue]:
        """All queues (active and inactive), in routing order."""
        self._require_tenant(tenant_id)
        return self.queues.list(tenant_id)

    def get(self, tenant_id: uuid.UUID, queue_id: uuid.UUID) -> Queue:
        queue = self.queues.get(tenant_id, queue_id)
        if queue is None:
            raise NotFoundError(f"Queue {queue_id} not found.")
        return queue

    def create(self, tenant_id: uuid.UUID, data: QueueCreate) -> Queue:
        self._require_tenant(tenant_id)
        queue = Queue(
            tenant_id=tenant_id,
            name=data.name,
            description=data.description,
            priority=data.priority,
            is_active=data.is_active,
            match_criteria=data.match_criteria.model_dump(),
            settings=data.settings.model_dump(),
        )
        self.queues.add(queue)
        self.session.commit()
        return queue

    def update(self, tenant_id: uuid.UUID, queue_id: uuid.UUID, data: QueueUpdate) -> Queue:
        """Change only the fields that were sent.

        Existing cases keep their queue; new cases are routed with the new rules.
        (Use "route" on a case to re-run matching for it.)
        """
        queue = self.get(tenant_id, queue_id)
        changes = data.model_dump(exclude_unset=True)
        for name in ("name", "description", "priority", "is_active"):
            if name in changes:
                setattr(queue, name, changes[name])
        if data.match_criteria is not None:
            queue.match_criteria = data.match_criteria.model_dump()
        if data.settings is not None:
            queue.settings = data.settings.model_dump()
        queue.updated_at = utcnow()
        self.session.commit()
        return queue

    def preview(self, tenant_id: uuid.UUID, req: RoutingPreviewRequest) -> RoutingPreview:
        """Which queue would this case land in? Explains every queue's result.

        With `draft`, tests unsaved queue settings (new, or replacing the queue
        `draft_queue_id`) without changing anything.
        """
        case = self.cases.get_by_number(tenant_id, req.case_number)
        if case is None:
            raise NotFoundError(f"Case {req.case_number} not found.")

        queues = self.queues.list(tenant_id, active_only=True)
        candidates = [to_candidate(q) for q in queues if q.id != req.draft_queue_id]

        draft: QueueCandidate | None = None
        if req.draft is not None and req.draft.is_active:
            existing = (
                self.queues.get(tenant_id, req.draft_queue_id) if req.draft_queue_id else None
            )
            draft = QueueCandidate(
                id=req.draft_queue_id,
                name=req.draft.name,
                priority=req.draft.priority,
                created_at=existing.created_at if existing else utcnow(),
                criteria=req.draft.match_criteria.model_dump(),
            )
            candidates.append(draft)

        texts = self.messages.customer_texts(tenant_id, case.id)
        result = route(candidates, case_context(case, texts))
        return RoutingPreview(
            winner_queue_id=result.winner.id if result.winner else None,
            winner_queue_name=result.winner.name if result.winner else None,
            evaluations=[
                QueueEvaluationRead(
                    queue_id=e.queue.id,
                    queue_name=e.queue.name,
                    priority=e.queue.priority,
                    matched=e.matched,
                    is_winner=e.queue is result.winner,
                    is_draft=e.queue is draft,
                    conditions=[
                        ConditionResultRead(
                            field=c.field,
                            op=c.op,
                            value=c.value,
                            matched=c.matched,
                            actual=c.actual,
                            description=describe_condition(c),
                        )
                        for c in e.conditions
                    ],
                )
                for e in result.evaluations
            ],
        )

    def fields(self, tenant_id: uuid.UUID) -> RoutingFields:
        """What the condition builder can offer: fields, suggested values, operators."""
        self._require_tenant(tenant_id)
        taxonomy = DEFAULT_TAXONOMY
        categories = sorted({c["name"] for t in taxonomy for c in t["categories"]})
        subcategories = sorted(
            {s["name"] for t in taxonomy for c in t["categories"] for s in c["subcategories"]}
        )
        suggestions: dict[str, list[str]] = {
            "category.type": [t["name"] for t in taxonomy],
            "category.category": categories,
            "category.subcategory": subcategories,
            "channel": CHANNELS,
            "customer.tier": self.customers.distinct_tiers(tenant_id),
            "message": [],
        }
        enrichment_fields = [
            RoutingField(
                key=f"{ENRICHMENT_PREFIX}{c.key}.{m['target']}",
                label=f"{c.name}: {m.get('label') or m['target']}",
                suggestions=[],
            )
            for c in self.connectors.list(tenant_id, active_only=True)
            for m in c.field_mappings
        ]
        return RoutingFields(
            fields=[
                RoutingField(key=key, label=label, suggestions=suggestions.get(key, []))
                for key, label in FIELDS.items()
            ]
            + enrichment_fields,
            operators=[
                RoutingOperator(key=key, label=label, takes_list=key in LIST_OPERATORS)
                for key, label in OPERATORS.items()
            ],
        )
