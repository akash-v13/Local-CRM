"""Data-access layer: the ONLY code that queries the database.

This is the equivalent of the Java layer that owned DocumentDB at the airline
— but as a module instead of a separate service. API routes and the worker
never write SQL/queries themselves; they go through services, which use
these repositories.

Rules:
- Every query is scoped by `tenant_id`. A record from another tenant is
  treated exactly like a missing record. This is the tenant-isolation
  guarantee; never add a query without it.
- Repositories don't commit. The calling service decides when the unit of
  work is complete and commits once.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.lifecycle import CaseStatus
from app.models import Case, CaseEvent, Customer, Message, Queue, Tenant


class TenantRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        return self.session.get(Tenant, tenant_id)

    def list(self) -> Sequence[Tenant]:
        """All tenants. Development only — no real deployment should expose this."""
        return self.session.scalars(select(Tenant).order_by(Tenant.created_at)).all()

    def add(self, tenant: Tenant) -> None:
        self.session.add(tenant)


class CustomerRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def find_by_email(self, tenant_id: uuid.UUID, email: str) -> Customer | None:
        stmt = select(Customer).where(Customer.tenant_id == tenant_id, Customer.email == email)
        return self.session.scalars(stmt).one_or_none()

    def distinct_tiers(self, tenant_id: uuid.UUID) -> list[str]:
        """Loyalty/value tiers seen on this tenant's customers (for rule-builder suggestions)."""
        stmt = (
            select(Customer.tier)
            .where(Customer.tenant_id == tenant_id, Customer.tier.is_not(None))
            .distinct()
            .order_by(Customer.tier)
        )
        return [t for t in self.session.scalars(stmt).all() if t]

    def add(self, customer: Customer) -> None:
        self.session.add(customer)


class CaseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_number(self, tenant_id: uuid.UUID, case_number: int) -> Case | None:
        stmt = select(Case).where(Case.tenant_id == tenant_id, Case.case_number == case_number)
        return self.session.scalars(stmt).one_or_none()

    def list(
        self,
        tenant_id: uuid.UUID,
        status: CaseStatus | None = None,
        queue_id: uuid.UUID | None = None,
        unrouted: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[Case]:
        stmt = select(Case).where(Case.tenant_id == tenant_id)
        if status is not None:
            stmt = stmt.where(Case.status == status.value)
        if queue_id is not None:
            stmt = stmt.where(Case.queue_id == queue_id)
        if unrouted:
            stmt = stmt.where(Case.queue_id.is_(None))
        stmt = stmt.order_by(Case.case_number.desc()).limit(limit).offset(offset)
        return self.session.scalars(stmt).all()

    def counts_by_queue_and_status(self, tenant_id: uuid.UUID) -> Sequence["QueueStatusCount"]:
        """One row per (queue, status) with the case count and oldest case.

        A single GROUP BY query, served by the (tenant_id, status, queue_id) index.
        """
        stmt = (
            select(Case.queue_id, Case.status, func.count(), func.min(Case.created_at))
            .where(Case.tenant_id == tenant_id)
            .group_by(Case.queue_id, Case.status)
        )
        return [
            QueueStatusCount(queue_id, CaseStatus(status), count, oldest)
            for queue_id, status, count, oldest in self.session.execute(stmt).all()
        ]

    def add(self, case: Case) -> None:
        self.session.add(case)


@dataclass(frozen=True)
class QueueStatusCount:
    queue_id: uuid.UUID | None
    status: CaseStatus
    count: int
    oldest_created_at: datetime


class QueueRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: uuid.UUID, queue_id: uuid.UUID) -> Queue | None:
        stmt = select(Queue).where(Queue.tenant_id == tenant_id, Queue.id == queue_id)
        return self.session.scalars(stmt).one_or_none()

    def list(self, tenant_id: uuid.UUID, active_only: bool = False) -> Sequence[Queue]:
        """Queues in routing order: priority, then creation time."""
        stmt = select(Queue).where(Queue.tenant_id == tenant_id)
        if active_only:
            stmt = stmt.where(Queue.is_active.is_(True))
        return self.session.scalars(stmt.order_by(Queue.priority, Queue.created_at)).all()

    def add(self, queue: Queue) -> None:
        self.session.add(queue)


class MessageRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_case(self, tenant_id: uuid.UUID, case_id: uuid.UUID) -> Sequence[Message]:
        stmt = (
            select(Message)
            .where(Message.tenant_id == tenant_id, Message.case_id == case_id)
            .order_by(Message.created_at)
        )
        return self.session.scalars(stmt).all()

    def customer_texts(self, tenant_id: uuid.UUID, case_id: uuid.UUID) -> list[str]:
        """Bodies of the customer's own messages, oldest first (used for keyword routing)."""
        return [
            m.body for m in self.list_for_case(tenant_id, case_id) if m.author_type == "customer"
        ]

    def add(self, message: Message) -> None:
        self.session.add(message)


class CaseEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_case(self, tenant_id: uuid.UUID, case_id: uuid.UUID) -> Sequence[CaseEvent]:
        stmt = (
            select(CaseEvent)
            .where(CaseEvent.tenant_id == tenant_id, CaseEvent.case_id == case_id)
            .order_by(CaseEvent.occurred_at)
        )
        return self.session.scalars(stmt).all()

    def add(self, event: CaseEvent) -> None:
        self.session.add(event)
