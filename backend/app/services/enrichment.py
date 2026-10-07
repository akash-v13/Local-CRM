"""Enriching a case: run its tenant's connectors, save the results, then route.

Called by the worker for `enrich_case` jobs. Split into three phases so no
database connection is held while waiting on external APIs:

1. Read  (short session):  the case and the active connectors.
                           The session is then closed; the loaded objects stay
                           readable but no connection is held.
2. Call  (no long session): run each connector in `run_order`. Later
                           connectors can use fields fetched by earlier ones.
                           (Token caching opens its own brief sessions.)
3. Write (short session):  store results, record an event, then route the case,
                           or move it to EnrichmentFailed if a *required*
                           connector failed. Retried if someone else saved the
                           case in the meantime (optimistic locking).

Only the mapped fields are stored on the case, never full API responses.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from app.config import Settings
from app.connectors.auth import AuthProvider
from app.connectors.context import contexts_for
from app.connectors.runner import run_connector
from app.domain.lifecycle import CaseStatus
from app.models import Case, CaseEvent, Connector, Job
from app.models.base import utcnow
from app.repositories import ConnectorRepository, JobRepository, MessageRepository
from app.schemas import ConnectorConfig, ConnectorRunResult
from app.security.ssrf import Resolver
from app.services.cases import CaseService
from app.services.connectors import auth_source, run_settings
from app.services.routing import enrichment_data

WRITE_ATTEMPTS = 3


@dataclass
class _PreparedConnector:
    id: uuid.UUID
    name: str
    config: ConnectorConfig


@dataclass
class _Outcome:
    connector: _PreparedConnector
    result: ConnectorRunResult


def _prepare(connector: Connector) -> _PreparedConnector:
    config = ConnectorConfig.model_validate(
        {c.key: getattr(connector, c.key) for c in Connector.__table__.columns}
    )
    return _PreparedConnector(connector.id, connector.name, config)


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=10 * attempts)


class EnrichmentService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        client: httpx.Client,
        settings: Settings,
        resolve: Resolver,
    ) -> None:
        self.session_factory = session_factory
        self.client = client
        self.settings = settings
        self.resolve = resolve

    def enrich_case(self, job_id: uuid.UUID) -> None:
        # ---- 1. Read --------------------------------------------------------------------
        with self.session_factory() as session:
            job = JobRepository(session).get(job_id)
            case = session.get(Case, job.case_id) if job and job.case_id else None
            if job is None or case is None:
                return
            texts = MessageRepository(session).customer_texts(case.tenant_id, case.id)
            connectors = ConnectorRepository(session).list(case.tenant_id, active_only=True)
            prepared = [_prepare(c) for c in connectors]
        # Session closed: `case` is detached but its loaded fields remain readable.

        # ---- 2. Call ------------------------------------------------------------------
        gathered = enrichment_data(case)
        outcomes: list[_Outcome] = []
        for connector in prepared:
            result = self._run_one(connector, case, texts, gathered)
            if result.status == "ok":
                gathered[connector.config.key] = result.data
            else:
                gathered.pop(connector.config.key, None)  # don't route on stale data
            outcomes.append(_Outcome(connector, result))

        # ---- 3. Write -----------------------------------------------------------------
        for attempt in range(1, WRITE_ATTEMPTS + 1):
            try:
                self._write(job_id, outcomes, texts)
                return
            except StaleDataError:
                if attempt == WRITE_ATTEMPTS:
                    raise

    def _run_one(
        self,
        connector: _PreparedConnector,
        case: Case,
        texts: list[str],
        gathered: dict[str, dict[str, Any]],
    ) -> ConnectorRunResult:
        template_ctx, routing_ctx = contexts_for(case, texts, gathered)
        runner_settings = run_settings(self.settings, self.resolve)
        provider = AuthProvider(self.session_factory, self.client, runner_settings)
        full = run_connector(
            connector.config,
            template_context=template_ctx,
            routing_context=routing_ctx,
            auth=auth_source(connector.config.credential_id, provider),
            client=self.client,
            settings=runner_settings,
        )
        # Keep only what the case needs: never the full response body.
        return ConnectorRunResult.model_validate(
            full.model_dump(exclude={"response_json", "response_text"})
        )

    def _write(self, job_id: uuid.UUID, outcomes: list[_Outcome], texts: list[str]) -> None:
        with self.session_factory() as session:
            job = JobRepository(session).get(job_id)
            case = session.get(Case, job.case_id) if job and job.case_id else None
            if job is None:
                return
            if case is None:  # deleted meanwhile
                job.status = "done"
                session.commit()
                return

            fetched_at = utcnow().isoformat()
            case.enrichment = {
                **case.enrichment,
                **{
                    o.connector.config.key: {
                        **o.result.model_dump(mode="json"),
                        "connectorId": str(o.connector.id),
                        "connectorName": o.connector.name,
                        "fetchedAt": fetched_at,
                        # JSONB doesn't keep key order; this does (connector run order).
                        "position": position,
                    }
                    for position, o in enumerate(outcomes)
                },
            }
            session.add(
                CaseEvent(
                    tenant_id=case.tenant_id,
                    case_id=case.id,
                    event_type="enrichment.completed",
                    actor_type="system",
                    data={
                        "connectors": [
                            {
                                "key": o.connector.config.key,
                                "name": o.connector.name,
                                "status": o.result.status,
                                "error": o.result.error,
                                "durationMs": o.result.duration_ms,
                            }
                            for o in outcomes
                        ]
                    },
                )
            )

            service = CaseService(session)
            if CaseStatus(case.status) is CaseStatus.INTAKE:
                failed_required = [
                    o.connector.name
                    for o in outcomes
                    if o.connector.config.required and o.result.status != "ok"
                ]
                if failed_required:
                    service.apply_transition(
                        case,
                        CaseStatus.ENRICHMENT_FAILED,
                        "system",
                        None,
                        "Required connector failed: " + ", ".join(failed_required),
                    )
                else:
                    service.apply_routing(case, texts, "system", None)
            case.updated_at = utcnow()
            job.status = "done"
            job.last_error = None
            session.commit()

    def job_failed(self, job_id: uuid.UUID, error: str) -> None:
        """An unexpected error (a bug, a database outage): retry later, or give up visibly.

        After the last attempt the case moves to EnrichmentFailed (if it was
        still in Intake), so it shows up on the dashboard instead of sitting
        silently.
        """
        with self.session_factory() as session:
            job = JobRepository(session).get(job_id)
            if job is None:
                return
            job.last_error = error[:2000]
            if job.attempts < job.max_attempts:
                job.status = "pending"
                job.run_after = utcnow() + _backoff(job.attempts)
                session.commit()
                return

            job.status = "failed"
            if job.kind == "issue_payout":
                from app.services.payouts import payout_gave_up  # avoids an import cycle

                payout_gave_up(session, job, error)
                session.commit()
                return
            if job.kind == "send_email":
                from app.services.email import send_failed  # avoids an import cycle

                send_failed(session, job, error)
                session.commit()
                return
            case = (
                session.get(Case, job.case_id)
                if job.case_id and job.kind == "enrich_case"
                else None
            )
            if case is not None:
                session.add(
                    CaseEvent(
                        tenant_id=case.tenant_id,
                        case_id=case.id,
                        event_type="enrichment.error",
                        actor_type="system",
                        reason="Enrichment couldn't complete after several attempts.",
                        data={"error": error[:500]},
                    )
                )
                if CaseStatus(case.status) is CaseStatus.INTAKE:
                    CaseService(session).apply_transition(
                        case, CaseStatus.ENRICHMENT_FAILED, "system", None, "Enrichment error"
                    )
            session.commit()


def claim_job(session_factory: sessionmaker[Session]) -> tuple[uuid.UUID, str] | None:
    """Claim the next due job and mark it running. Returns (job id, kind), or None."""
    with session_factory() as session:
        job: Job | None = JobRepository(session).claim_next()
        if job is None:
            return None
        job.status = "running"
        job.attempts += 1
        job.locked_at = utcnow()
        session.commit()
        return job.id, job.kind
