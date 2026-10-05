"""The intake pipeline: what every new case goes through, and what happened to each case.

    Case received → ① connector → ② connector → … → Routing → Compensation → Agent

- `definition`: the business-wide flow, built from the current configuration
  (active connectors in run order, queues, compensation rules). It also works
  out each step's **dependencies** from the placeholders in its request, e.g.
  `{{enrichment.shop_orders.trackingNumber}}` means "needs Shop orders first",
  and flags setups that can't work (a step using data from a later step).
- `executions` / `execution`: what actually happened per case, read from what
  enrichment, routing and compensation already store on the case. Nothing new
  is recorded for this view.

Steps run one after another today (no parallel branches).
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from app.domain.compensation import TYPE_LABELS
from app.domain.errors import NotFoundError
from app.domain.routing import ConditionResult, describe_condition
from app.domain.templates import placeholders
from app.models import Case, Connector
from app.repositories import (
    CaseEventRepository,
    CaseRepository,
    CompensationRuleRepository,
    ConnectorRepository,
    CredentialRepository,
    QueueRepository,
    TenantRepository,
)
from app.schemas import (
    CompensationSettingsData,
    ExecutionDetail,
    ExecutionOutcome,
    ExecutionRouting,
    ExecutionStep,
    ExecutionSummary,
    PipelineConnectorStep,
    PipelineDefinition,
    PipelineDependency,
    PipelineQueue,
    PipelineRule,
    PipelineStepField,
    QueueSettings,
    RequestPreview,
)

ENRICHMENT = "enrichment."


def describe_criteria(criteria: dict[str, Any]) -> list[str]:
    """Conditions in plain words, e.g. ['Category is "Delivery"']."""
    return [
        describe_condition(ConditionResult(c["field"], c["op"], c["value"], False, None))
        for c in criteria.get("conditions") or []
    ]


def describe_outcome(outcome: dict[str, Any]) -> str:
    label = TYPE_LABELS.get(str(outcome.get("type")), str(outcome.get("type")))
    if outcome.get("type") not in ("refund", "store_credit", "voucher", "points"):
        return label
    if outcome.get("amount_mode") == "percent":
        amount = f"{outcome.get('percent'):g}% of {outcome.get('percent_of')}"
    else:
        amount = f"{outcome.get('amount')}"
    cap = f", max {outcome['cap']:g}" if outcome.get("cap") is not None else ""
    approval = ", always needs approval" if outcome.get("requires_approval") else ""
    return f"{label}: {amount}{cap}{approval}"


def dependencies(connector: Connector) -> list[PipelineDependency]:
    """Every placeholder in the request (URL, headers, body), in order, without repeats."""
    texts = [
        connector.url_template,
        *dict(connector.headers).values(),
        connector.body_template or "",
    ]
    seen: dict[str, PipelineDependency] = {}
    for path in (p for t in texts for p in placeholders(t)):
        if path in seen:
            continue
        if path.startswith(ENRICHMENT):
            key, _, field = path.removeprefix(ENRICHMENT).partition(".")
            seen[path] = PipelineDependency(source="step", path=path, step_key=key, field=field)
        else:
            seen[path] = PipelineDependency(source="case", path=path)
    return list(seen.values())


def category_label(case: Case) -> str:
    effective = case.category.get("effective") or {}
    parts = [effective.get(k) for k in ("type", "category", "subcategory")]
    return " › ".join(str(p) for p in parts if p) or "Uncategorized"


class PipelineService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.connectors = ConnectorRepository(session)
        self.credentials = CredentialRepository(session)
        self.queues = QueueRepository(session)
        self.rules = CompensationRuleRepository(session)
        self.cases = CaseRepository(session)
        self.events = CaseEventRepository(session)

    def _tenant_settings(self, tenant_id: uuid.UUID) -> CompensationSettingsData:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        return CompensationSettingsData.model_validate(tenant.compensation_settings or {})

    # ----- definition -----------------------------------------------------------------------

    def definition(self, tenant_id: uuid.UUID) -> PipelineDefinition:
        settings = self._tenant_settings(tenant_id)
        all_connectors = self.connectors.list(tenant_id)
        active = [c for c in all_connectors if c.is_active]  # already in run order
        credentials = {c.id: c for c in self.credentials.list(tenant_id)}
        position = {c.key: i for i, c in enumerate(active, start=1)}
        saved = {c.key: {m["target"] for m in c.field_mappings} for c in active}
        names = {c.key: c.name for c in all_connectors}

        steps: list[PipelineConnectorStep] = []
        for i, c in enumerate(active, start=1):
            uses = dependencies(c)
            problems: list[str] = []
            for dep in (d for d in uses if d.source == "step"):
                key = dep.step_key or ""
                if key not in position:
                    state = "inactive" if key in names else "not a connector"
                    problems.append(f"Uses {dep.path}, but '{names.get(key, key)}' is {state}.")
                elif position[key] >= i:
                    problems.append(
                        f"Uses {dep.path}, but {names[key]} runs after this step "
                        f"(step {position[key]}). Give this connector a higher run order."
                    )
                elif dep.field not in saved[key]:
                    problems.append(
                        f"Uses {dep.path}, but {names[key]} doesn't save a field called "
                        f"'{dep.field}'."
                    )
            credential = credentials.get(c.credential_id) if c.credential_id else None
            criteria = dict(c.run_when)
            steps.append(
                PipelineConnectorStep(
                    position=i,
                    connector_id=c.id,
                    key=c.key,
                    name=c.name,
                    description=c.description,
                    method=c.method,
                    url_template=c.url_template,
                    credential_name=credential.name if credential else None,
                    credential_kind=credential.kind if credential else None,
                    required=c.required,
                    timeout_seconds=c.timeout_seconds,
                    max_retries=c.max_retries,
                    run_when=describe_criteria(criteria),
                    run_when_match="any" if criteria.get("match") == "any" else "all",
                    fields=[
                        PipelineStepField(target=m["target"], label=m.get("label"), path=m["path"])
                        for m in c.field_mappings
                    ],
                    uses=uses,
                    problems=problems,
                )
            )

        queues = []
        for q in self.queues.list(tenant_id, active_only=True):
            queue_settings = QueueSettings.model_validate(q.settings)
            criteria = dict(q.match_criteria)
            queues.append(
                PipelineQueue(
                    id=q.id,
                    name=q.name,
                    priority=q.priority,
                    conditions=describe_criteria(criteria),
                    match="any" if criteria.get("match") == "any" else "all",
                    ai_drafting=queue_settings.gen_ai_allowed,
                    ai_model=queue_settings.ai_model if queue_settings.gen_ai_allowed else None,
                )
            )
        rules = [
            PipelineRule(
                id=r.id,
                name=r.name,
                priority=r.priority,
                conditions=describe_criteria(dict(r.match_criteria)),
                outcome=describe_outcome(dict(r.outcome)),
            )
            for r in self.rules.list(tenant_id, active_only=True)
        ]
        return PipelineDefinition(
            connectors=steps,
            inactive_connectors=[c.name for c in all_connectors if not c.is_active],
            queues=queues,
            compensation_rules=rules,
            compensation_guardrails=(
                f"Approval if the customer was compensated {settings.repeat_max_count}+ time(s) "
                f"in {settings.repeat_lookback_days} days, or the amount is above the queue's "
                "approval threshold."
            ),
        )

    # ----- executions -----------------------------------------------------------------------

    def _steps(self, case: Case, active: Sequence[Connector], detail: bool) -> list[ExecutionStep]:
        """One entry per step of today's pipeline, plus results from steps since removed."""
        results: dict[str, dict[str, Any]] = {
            k: v for k, v in case.enrichment.items() if isinstance(v, dict)
        }
        waiting = case.status == "Intake"
        steps: list[ExecutionStep] = []
        for i, c in enumerate(active, start=1):
            raw = results.pop(c.key, None)
            if raw is None:
                steps.append(
                    ExecutionStep(
                        key=c.key,
                        name=c.name,
                        position=i,
                        status="pending" if waiting else "not_run",
                        error=None if waiting else "Added after this case was enriched.",
                    )
                )
            else:
                steps.append(self._step(c.key, c.name, i, raw, detail))
        leftovers = sorted(results.items(), key=lambda kv: kv[1].get("position", 0))
        for key, raw in leftovers:
            steps.append(self._step(key, str(raw.get("connectorName") or key), None, raw, detail))
        return steps

    @staticmethod
    def _step(
        key: str, name: str, position: int | None, raw: dict[str, Any], detail: bool
    ) -> ExecutionStep:
        status = raw.get("status") if raw.get("status") in ("ok", "failed", "skipped") else "failed"
        step = ExecutionStep(
            key=key,
            name=name,
            position=position,
            status=status,
            error=raw.get("error"),
            http_status=raw.get("http_status"),
            duration_ms=raw.get("duration_ms"),
            fetched_at=raw.get("fetchedAt"),
        )
        if detail:
            step.request = (
                RequestPreview.model_validate(raw["request"]) if raw.get("request") else None
            )
            step.data = dict(raw.get("data") or {})
            step.missing = list(raw.get("missing") or [])
        return step

    @staticmethod
    def _outcome(steps: list[ExecutionStep], case: Case) -> ExecutionOutcome:
        ran = [s for s in steps if s.status in ("ok", "failed", "skipped")]
        if any(s.status == "pending" for s in steps):
            return "in_progress"
        if not ran:
            return "no_enrichment"
        failed = [s for s in ran if s.status == "failed"]
        if not failed:
            return "ok"
        return (
            "failed" if len(failed) == len(ran) or case.status == "EnrichmentFailed" else "partial"
        )

    def _summary(self, case: Case, active: Sequence[Connector], detail: bool) -> dict[str, Any]:
        steps = self._steps(case, active, detail)
        decision = case.decisions.get("compensation") or {}
        return {
            "case_number": case.case_number,
            "created_at": case.created_at,
            "customer_name": case.customer.display_name,
            "customer_email": case.customer.email,
            "category": category_label(case),
            "case_status": case.status,
            "outcome": self._outcome(steps, case),
            "steps": steps,
            "total_duration_ms": sum(s.duration_ms or 0 for s in steps),
            "queue_name": case.queue.name if case.queue else None,
            "compensation_status": decision.get("status"),
            "compensation_label": decision.get("label"),
        }

    def executions(
        self, tenant_id: uuid.UUID, *, outcome: str | None = None, limit: int = 50
    ) -> list[ExecutionSummary]:
        """Recent cases' runs, newest first. `outcome` filters (e.g. "failed")."""
        self._tenant_settings(tenant_id)
        active = self.connectors.list(tenant_id, active_only=True)
        rows: list[ExecutionSummary] = []
        # Scan a bit more than asked so filtering still fills the page.
        for case in self.cases.list(tenant_id, limit=limit * (4 if outcome else 1)):
            summary = ExecutionSummary(**self._summary(case, active, detail=False))
            if outcome and summary.outcome != outcome:
                continue
            rows.append(summary)
            if len(rows) >= limit:
                break
        return rows

    def execution(self, tenant_id: uuid.UUID, case_number: int) -> ExecutionDetail:
        case = self.cases.get_by_number(tenant_id, case_number)
        if case is None:
            raise NotFoundError(f"Case {case_number} not found.")
        active = self.connectors.list(tenant_id, active_only=True)
        events = self.events.list_for_case(tenant_id, case.id)
        routed = next(
            (e for e in reversed(events) if e.event_type in ("case.routed", "case.rerouted")), None
        )
        enriched = next(
            (e for e in reversed(events) if e.event_type == "enrichment.completed"), None
        )
        matched: list[str] = []
        if routed is not None and routed.event_type == "case.routed":
            matched = list(routed.data.get("matchedConditions") or [])
        elif routed is not None:
            matched = [f"Moved manually by {routed.actor_id or 'an agent'}"]
        return ExecutionDetail(
            **self._summary(case, active, detail=True),
            routing=ExecutionRouting(
                queue_name=case.queue.name if case.queue else None,
                matched_conditions=matched,
                routed_at=routed.occurred_at if routed else None,
            ),
            compensation=case.decisions.get("compensation"),
            enriched_at=enriched.occurred_at if enriched else None,
        )
