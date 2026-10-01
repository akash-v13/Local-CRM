"""Operational reporting."""

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from app.domain.errors import NotFoundError
from app.domain.lifecycle import OPEN_STATUSES, CaseStatus
from app.models.base import utcnow
from app.repositories import CaseRepository, QueueRepository, TenantRepository
from app.schemas import QueueReport, QueueReportRow

UNROUTED_LABEL = "Unrouted"


class ReportService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.queues = QueueRepository(session)
        self.cases = CaseRepository(session)

    def queue_report(self, tenant_id: uuid.UUID) -> QueueReport:
        """Case counts per queue and status, plus totals.

        Every queue gets a row (even with zero cases), in routing order. Cases
        that no queue matched appear in an extra "Unrouted" row.
        """
        if self.tenants.get(tenant_id) is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")

        counts: dict[uuid.UUID | None, dict[CaseStatus, int]] = defaultdict(dict)
        oldest_open: dict[uuid.UUID | None, datetime] = {}
        totals: dict[CaseStatus, int] = defaultdict(int)

        for row in self.cases.counts_by_queue_and_status(tenant_id):
            counts[row.queue_id][row.status] = row.count
            totals[row.status] += row.count
            if row.status in OPEN_STATUSES:
                current = oldest_open.get(row.queue_id)
                if current is None or row.oldest_created_at < current:
                    oldest_open[row.queue_id] = row.oldest_created_at

        def make_row(
            queue_id: uuid.UUID | None, name: str, priority: int | None, active: bool
        ) -> QueueReportRow:
            by_status = counts.get(queue_id, {})
            return QueueReportRow(
                queue_id=queue_id,
                queue_name=name,
                priority=priority,
                is_active=active,
                counts=by_status,
                open_total=sum(n for s, n in by_status.items() if s in OPEN_STATUSES),
                oldest_open_at=oldest_open.get(queue_id),
            )

        rows = [
            make_row(q.id, q.name, q.priority, q.is_active) for q in self.queues.list(tenant_id)
        ]
        if None in counts:
            rows.append(make_row(None, UNROUTED_LABEL, None, True))

        return QueueReport(
            generated_at=utcnow(),
            totals=dict(totals),
            open_total=sum(n for s, n in totals.items() if s in OPEN_STATUSES),
            rows=rows,
        )
