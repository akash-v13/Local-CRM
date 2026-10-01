"""Tenant operations."""

import uuid
from collections.abc import Sequence

from sqlalchemy.orm import Session

from app.domain.errors import NotFoundError
from app.models import Queue, Tenant
from app.repositories import QueueRepository, TenantRepository
from app.schemas import QueueSettings, TenantCreate

# Every new tenant gets a catch-all queue, so no case is ever left unrouted
# out of the box. Managers can rename, reprioritise or deactivate it.
DEFAULT_QUEUE_NAME = "General"
DEFAULT_QUEUE_PRIORITY = 1000


class TenantService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.queues = QueueRepository(session)

    def create(self, data: TenantCreate) -> Tenant:
        """Create a tenant together with its default catch-all queue."""
        tenant = Tenant(name=data.name)
        self.tenants.add(tenant)
        self.session.flush()  # assigns tenant.id
        self.queues.add(
            Queue(
                tenant_id=tenant.id,
                name=DEFAULT_QUEUE_NAME,
                description=(
                    "Catch-all: receives every case no other queue matches. "
                    "Keep it last (highest priority number)."
                ),
                priority=DEFAULT_QUEUE_PRIORITY,
                is_active=True,
                match_criteria={"match": "all", "conditions": []},
                settings=QueueSettings().model_dump(),
            )
        )
        self.session.commit()
        return tenant

    def list(self) -> Sequence[Tenant]:
        return self.tenants.list()

    def get(self, tenant_id: uuid.UUID) -> Tenant:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        return tenant
