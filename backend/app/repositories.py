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
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.domain.lifecycle import CaseStatus
from app.models import (
    Case,
    CaseEvent,
    CompensationRule,
    Connector,
    Credential,
    Customer,
    Job,
    Message,
    Queue,
    Tenant,
)
from app.models.base import utcnow


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

    def for_customer(self, tenant_id: uuid.UUID, customer_id: uuid.UUID) -> Sequence[Case]:
        """All of a customer's cases, oldest first (for the repeat-claimant check)."""
        stmt = (
            select(Case)
            .where(Case.tenant_id == tenant_id, Case.customer_id == customer_id)
            .order_by(Case.case_number)
        )
        return self.session.scalars(stmt).all()

    def created_since(
        self, tenant_id: uuid.UUID, since: datetime, limit: int = 5000
    ) -> Sequence[Case]:
        """Cases created since `since`, oldest first (for the compensation backtest)."""
        stmt = (
            select(Case)
            .where(Case.tenant_id == tenant_id, Case.created_at >= since)
            .order_by(Case.case_number)
            .limit(limit)
        )
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

    def customer_texts_for_cases(
        self, tenant_id: uuid.UUID, case_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, list[str]]:
        """customer_texts for many cases in one query."""
        texts: dict[uuid.UUID, list[str]] = {case_id: [] for case_id in case_ids}
        if not case_ids:
            return texts
        stmt = (
            select(Message)
            .where(
                Message.tenant_id == tenant_id,
                Message.case_id.in_(case_ids),
                Message.author_type == "customer",
            )
            .order_by(Message.created_at)
        )
        for m in self.session.scalars(stmt):
            texts[m.case_id].append(m.body)
        return texts

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


class ConnectorRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: uuid.UUID, connector_id: uuid.UUID) -> Connector | None:
        stmt = select(Connector).where(
            Connector.tenant_id == tenant_id, Connector.id == connector_id
        )
        return self.session.scalars(stmt).one_or_none()

    def list(self, tenant_id: uuid.UUID, active_only: bool = False) -> Sequence[Connector]:
        """Connectors in the order they run: run_order, then creation time."""
        stmt = select(Connector).where(Connector.tenant_id == tenant_id)
        if active_only:
            stmt = stmt.where(Connector.is_active.is_(True))
        return self.session.scalars(stmt.order_by(Connector.run_order, Connector.created_at)).all()

    def has_active(self, tenant_id: uuid.UUID) -> bool:
        stmt = select(Connector.id).where(
            Connector.tenant_id == tenant_id, Connector.is_active.is_(True)
        )
        return self.session.scalars(stmt.limit(1)).first() is not None

    def add(self, connector: Connector) -> None:
        self.session.add(connector)


# A "running" job whose worker hasn't finished within this time is assumed dead
# (crashed or killed) and is picked up again.
STALE_JOB_AFTER = timedelta(minutes=10)


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, job: Job) -> None:
        self.session.add(job)

    def get(self, job_id: uuid.UUID) -> Job | None:
        return self.session.get(Job, job_id)

    def claim_next(self) -> Job | None:
        """Lock the next due job so no other worker takes it.

        `FOR UPDATE SKIP LOCKED` makes concurrent workers skip rows another
        worker has locked instead of waiting. (SQLite, used in tests, ignores it.)
        """
        now = utcnow()
        stmt = (
            select(Job)
            .where(
                or_(
                    and_(Job.status == "pending", Job.run_after <= now),
                    and_(Job.status == "running", Job.locked_at < now - STALE_JOB_AFTER),
                )
            )
            .order_by(Job.run_after)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return self.session.scalars(stmt).first()

    def pending_for_case(self, case_id: uuid.UUID) -> Job | None:
        stmt = select(Job).where(Job.case_id == case_id, Job.status.in_(("pending", "running")))
        return self.session.scalars(stmt.limit(1)).first()


class CredentialRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: uuid.UUID, credential_id: uuid.UUID) -> Credential | None:
        stmt = select(Credential).where(
            Credential.tenant_id == tenant_id, Credential.id == credential_id
        )
        return self.session.scalars(stmt).one_or_none()

    def list(self, tenant_id: uuid.UUID) -> Sequence[Credential]:
        stmt = select(Credential).where(Credential.tenant_id == tenant_id)
        return self.session.scalars(stmt.order_by(Credential.name)).all()

    def add(self, credential: Credential) -> None:
        self.session.add(credential)


class CompensationRuleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, tenant_id: uuid.UUID, rule_id: uuid.UUID) -> CompensationRule | None:
        stmt = select(CompensationRule).where(
            CompensationRule.tenant_id == tenant_id, CompensationRule.id == rule_id
        )
        return self.session.scalars(stmt).one_or_none()

    def list(self, tenant_id: uuid.UUID, active_only: bool = False) -> Sequence[CompensationRule]:
        """Rules in decision order: priority, then creation time."""
        stmt = select(CompensationRule).where(CompensationRule.tenant_id == tenant_id)
        if active_only:
            stmt = stmt.where(CompensationRule.is_active.is_(True))
        return self.session.scalars(
            stmt.order_by(CompensationRule.priority, CompensationRule.created_at)
        ).all()

    def add(self, rule: CompensationRule) -> None:
        self.session.add(rule)
