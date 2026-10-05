"""Compensation matrix: rule management, decisions on cases, approvals, live test, backtest.

The decision logic itself is pure and lives in app/domain/compensation.py; this
module loads what it needs from the database and records the result.

A case's decision is stored as `case.decisions["compensation"]`
(`CompensationDecisionData`) and every change is an event on the case:
compensation.decided / compensation.approved / compensation.rejected.
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.domain.compensation import (
    Decision,
    PastCompensation,
    RuleCandidate,
    Settings,
    decide,
)
from app.domain.errors import ConflictError, NotFoundError
from app.domain.routing import describe_condition
from app.models import Case, CaseEvent, CompensationRule
from app.models.base import utcnow
from app.repositories import (
    CaseEventRepository,
    CaseRepository,
    CompensationRuleRepository,
    MessageRepository,
    TenantRepository,
)
from app.schemas import (
    ActorType,
    CompensationDecisionData,
    CompensationPreview,
    CompensationPreviewRequest,
    CompensationReview,
    CompensationRuleCreate,
    CompensationSettingsData,
    CompensationStatus,
    ConditionResultRead,
    PastCompensationRead,
    QueueSettings,
    RuleEvaluationRead,
    SimulationRequest,
    SimulationResult,
    SimulationRow,
)
from app.services.routing import case_context

KEY = "compensation"
# Statuses a person has settled; automatic decisions never overwrite them.
REVIEWED = ("approved", "rejected")


def to_candidate(rule: CompensationRule) -> RuleCandidate:
    return RuleCandidate(
        id=rule.id,
        name=rule.name,
        priority=rule.priority,
        created_at=rule.created_at,
        criteria=dict(rule.match_criteria),
        outcome=dict(rule.outcome),
    )


def draft_candidate(
    draft: CompensationRuleCreate, draft_id: uuid.UUID | None, existing: CompensationRule | None
) -> RuleCandidate:
    return RuleCandidate(
        id=draft_id,
        name=draft.name,
        priority=draft.priority,
        created_at=existing.created_at if existing else utcnow(),
        criteria=draft.match_criteria.model_dump(),
        outcome=draft.outcome.model_dump(),
    )


def stored_decision(case: Case) -> CompensationDecisionData | None:
    raw = case.decisions.get(KEY)
    return CompensationDecisionData.model_validate(raw) if raw else None


def past_compensation(case: Case) -> PastCompensation | None:
    """The compensation this case actually gave, if any (approved and not "none")."""
    decision = stored_decision(case)
    if decision is None or decision.status != "approved":
        return None
    return PastCompensation(
        case.case_number, decision.decided_at, decision.type or "", decision.amount
    )


def to_data(decision: Decision, decided_by: str, now: datetime) -> CompensationDecisionData:
    status: CompensationStatus
    if decision.rule is None:
        status = "no_match"
    elif decision.type == "none":
        status = "no_compensation"
    elif decision.needs_approval:
        status = "pending_approval"
    else:
        status = "approved"
    winner = next((e for e in decision.evaluations if e.rule is decision.rule), None)
    return CompensationDecisionData(
        status=status,
        rule_id=decision.rule.id if decision.rule else None,
        rule_name=decision.rule.name if decision.rule else None,
        type=decision.type,
        amount=decision.amount,
        currency=decision.currency,
        label=decision.label,
        amount_explanation=decision.amount_explanation,
        approval_reasons=decision.approval_reasons,
        matched_conditions=[describe_condition(c) for c in winner.conditions] if winner else [],
        history=[
            PastCompensationRead(
                case_number=h.case_number, decided_at=h.decided_at, type=h.type, amount=h.amount
            )
            for h in decision.history
        ],
        decided_at=now,
        decided_by=decided_by,
    )


def evaluations_read(decision: Decision, draft: RuleCandidate | None) -> list[RuleEvaluationRead]:
    return [
        RuleEvaluationRead(
            rule_id=e.rule.id,
            rule_name=e.rule.name,
            priority=e.rule.priority,
            matched=e.matched,
            is_winner=e.rule is decision.rule,
            is_draft=e.rule is draft,
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
        for e in decision.evaluations
    ]


class CompensationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.tenants = TenantRepository(session)
        self.rules = CompensationRuleRepository(session)
        self.cases = CaseRepository(session)
        self.messages = MessageRepository(session)
        self.events = CaseEventRepository(session)

    # ----- rules and settings -------------------------------------------------------------

    def _require_tenant(self, tenant_id: uuid.UUID) -> None:
        if self.tenants.get(tenant_id) is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")

    def list_rules(self, tenant_id: uuid.UUID) -> Sequence[CompensationRule]:
        """All rules (active and inactive) in decision order."""
        self._require_tenant(tenant_id)
        return self.rules.list(tenant_id)

    def get_rule(self, tenant_id: uuid.UUID, rule_id: uuid.UUID) -> CompensationRule:
        rule = self.rules.get(tenant_id, rule_id)
        if rule is None:
            raise NotFoundError(f"Compensation rule {rule_id} not found.")
        return rule

    def save_rule(
        self, tenant_id: uuid.UUID, data: CompensationRuleCreate, rule_id: uuid.UUID | None = None
    ) -> CompensationRule:
        """Create a rule, or replace one. Existing decisions on cases are not changed."""
        self._require_tenant(tenant_id)
        rule = (
            self.get_rule(tenant_id, rule_id) if rule_id else CompensationRule(tenant_id=tenant_id)
        )
        rule.name = data.name
        rule.description = data.description
        rule.priority = data.priority
        rule.is_active = data.is_active
        rule.match_criteria = data.match_criteria.model_dump()
        rule.outcome = data.outcome.model_dump()
        rule.updated_at = utcnow()
        if rule_id is None:
            self.rules.add(rule)
        self.session.commit()
        return rule

    def get_settings(self, tenant_id: uuid.UUID) -> CompensationSettingsData:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        return CompensationSettingsData.model_validate(tenant.compensation_settings or {})

    def save_settings(
        self, tenant_id: uuid.UUID, data: CompensationSettingsData
    ) -> CompensationSettingsData:
        tenant = self.tenants.get(tenant_id)
        if tenant is None:
            raise NotFoundError(f"Tenant {tenant_id} not found.")
        tenant.compensation_settings = data.model_dump()
        self.session.commit()
        return data

    def _domain_settings(self, tenant_id: uuid.UUID) -> Settings:
        s = self.get_settings(tenant_id)
        return Settings(s.repeat_lookback_days, s.repeat_max_count, s.currency)

    # ----- deciding -----------------------------------------------------------------------

    def _decide(
        self,
        case: Case,
        texts: list[str],
        rules: Sequence[RuleCandidate],
        settings: Settings,
        history: Sequence[PastCompensation] | None = None,
        now: datetime | None = None,
    ) -> Decision:
        if history is None:
            history = [
                p
                for other in self.cases.for_customer(case.tenant_id, case.customer_id)
                if other.id != case.id and (p := past_compensation(other)) is not None
            ]
        threshold = (
            QueueSettings.model_validate(case.queue.settings).approval_threshold
            if case.queue
            else None
        )
        return decide(
            rules,
            case_context(case, texts),
            history=history,
            settings=settings,
            approval_threshold=threshold,
            now=now or utcnow(),
        )

    def decide_for_case(
        self,
        case: Case,
        texts: list[str],
        actor_type: ActorType,
        actor_id: str | None,
        *,
        only_if_undecided: bool,
    ) -> CompensationDecisionData | None:
        """Run the matrix for a case and store the decision with an event. Does NOT commit.

        Automatic runs (after routing) use `only_if_undecided`, so a decision
        that already exists is never changed behind anyone's back.
        """
        existing = stored_decision(case)
        if existing is not None and (only_if_undecided or existing.status in REVIEWED):
            if not only_if_undecided:
                raise ConflictError(
                    f"Compensation was already {existing.status.replace('_', ' ')}"
                    f"{f' by {existing.reviewed_by}' if existing.reviewed_by else ''}; "
                    "it can't be decided again."
                )
            return None
        rules = [to_candidate(r) for r in self.rules.list(case.tenant_id, active_only=True)]
        if not rules and only_if_undecided:
            return None  # the business hasn't set up a matrix: nothing to record
        now = utcnow()
        decision = self._decide(case, texts, rules, self._domain_settings(case.tenant_id), now=now)
        data = to_data(decision, actor_id or "system", now)
        case.decisions = {**case.decisions, KEY: data.model_dump(mode="json")}
        self.events.add(
            CaseEvent(
                tenant_id=case.tenant_id,
                case_id=case.id,
                event_type="compensation.decided",
                actor_type=actor_type,
                actor_id=actor_id,
                reason="; ".join(data.approval_reasons) or None,
                data={
                    "status": data.status,
                    "ruleName": data.rule_name,
                    "label": data.label,
                    "amount": data.amount,
                    "matchedConditions": data.matched_conditions,
                },
            )
        )
        return data

    def decide_again(
        self, tenant_id: uuid.UUID, case_number: int, actor_id: str | None
    ) -> CompensationDecisionData:
        """Re-run the matrix for a case (e.g. after enrichment or rule changes)."""
        case = self._case(tenant_id, case_number)
        texts = self.messages.customer_texts(tenant_id, case.id)
        data = self.decide_for_case(
            case, texts, "human" if actor_id else "system", actor_id, only_if_undecided=False
        )
        assert data is not None
        case.updated_at = utcnow()
        self.session.commit()
        return data

    def review(
        self, tenant_id: uuid.UUID, case_number: int, req: CompensationReview, *, approve: bool
    ) -> CompensationDecisionData:
        """Approve or reject a decision that's waiting for approval."""
        case = self._case(tenant_id, case_number)
        decision = stored_decision(case)
        if decision is None or decision.status != "pending_approval":
            state = decision.status.replace("_", " ") if decision else "not decided"
            raise ConflictError(
                f"Only decisions waiting for approval can be reviewed (this one is {state})."
            )
        if not approve and not (req.note or "").strip():
            raise ConflictError("Give a reason for rejecting.")
        decision.status = "approved" if approve else "rejected"
        decision.reviewed_by = req.actor_id
        decision.reviewed_at = utcnow()
        decision.review_note = req.note
        case.decisions = {**case.decisions, KEY: decision.model_dump(mode="json")}
        self.events.add(
            CaseEvent(
                tenant_id=tenant_id,
                case_id=case.id,
                event_type=f"compensation.{decision.status}",
                actor_type="human",
                actor_id=req.actor_id,
                reason=req.note,
                data={"label": decision.label, "amount": decision.amount},
            )
        )
        case.updated_at = utcnow()
        self.session.commit()
        return decision

    def _case(self, tenant_id: uuid.UUID, case_number: int) -> Case:
        case = self.cases.get_by_number(tenant_id, case_number)
        if case is None:
            raise NotFoundError(f"Case {case_number} not found.")
        return case

    # ----- live test and backtest ---------------------------------------------------------

    def _rules_with_draft(
        self,
        tenant_id: uuid.UUID,
        draft: CompensationRuleCreate | None,
        draft_rule_id: uuid.UUID | None,
    ) -> tuple[list[RuleCandidate], RuleCandidate | None]:
        rules = [
            to_candidate(r)
            for r in self.rules.list(tenant_id, active_only=True)
            if r.id != draft_rule_id
        ]
        candidate = None
        if draft is not None and draft.is_active:
            existing = self.rules.get(tenant_id, draft_rule_id) if draft_rule_id else None
            candidate = draft_candidate(draft, draft_rule_id, existing)
            rules.append(candidate)
        return rules, candidate

    def preview(self, tenant_id: uuid.UUID, req: CompensationPreviewRequest) -> CompensationPreview:
        """What would the matrix decide for this case (optionally with an unsaved rule)?
        Explains every rule's result. Changes nothing."""
        case = self._case(tenant_id, req.case_number)
        rules, draft = self._rules_with_draft(tenant_id, req.draft, req.draft_rule_id)
        texts = self.messages.customer_texts(tenant_id, case.id)
        now = utcnow()
        decision = self._decide(case, texts, rules, self._domain_settings(tenant_id), now=now)
        return CompensationPreview(
            decision=to_data(decision, "preview", now),
            evaluations=evaluations_read(decision, draft),
        )

    def simulate(self, tenant_id: uuid.UUID, req: SimulationRequest) -> SimulationResult:
        """Backtest: run the matrix over recent cases, oldest first, as if it had been live
        (each simulated compensation counts toward the customer's repeat-claim history).
        Changes nothing."""
        self._require_tenant(tenant_id)
        settings = self._domain_settings(tenant_id)
        rules, draft = self._rules_with_draft(tenant_id, req.draft, req.draft_rule_id)
        cases = self.cases.created_since(tenant_id, utcnow() - timedelta(days=req.days))
        texts = self.messages.customer_texts_for_cases(tenant_id, [c.id for c in cases])

        history: dict[uuid.UUID, list[PastCompensation]] = defaultdict(list)
        # Keyed by id(): rules hold dicts, so they can't be hashed.
        rows: dict[int, tuple[RuleCandidate, SimulationRow]] = {}
        no_match: list[int] = []
        for case in cases:
            decision = self._decide(
                case,
                texts[case.id],
                rules,
                settings,
                history=history[case.customer_id],
                now=case.created_at,
            )
            if decision.rule is None:
                no_match.append(case.case_number)
                continue
            _, row = rows.setdefault(
                id(decision.rule),
                (
                    decision.rule,
                    SimulationRow(
                        rule_id=decision.rule.id,
                        rule_name=decision.rule.name,
                        is_draft=decision.rule is draft,
                        cases=0,
                        needs_approval=0,
                        total_amount=0.0,
                        example_case_numbers=[],
                    ),
                ),
            )
            row.cases += 1
            row.needs_approval += int(decision.needs_approval)
            row.total_amount = round(row.total_amount + (decision.amount or 0), 2)
            if len(row.example_case_numbers) < 5:
                row.example_case_numbers.append(case.case_number)
            if decision.type not in (None, "none"):
                history[case.customer_id].append(
                    PastCompensation(
                        case.case_number, case.created_at, decision.type or "", decision.amount
                    )
                )

        ordered = sorted(rows.values(), key=lambda kv: (kv[0].priority, kv[0].created_at))
        return SimulationResult(
            days=req.days,
            cases_checked=len(cases),
            cases_matched=len(cases) - len(no_match),
            needs_approval=sum(r.needs_approval for _, r in ordered),
            total_amount=round(sum(r.total_amount for _, r in ordered), 2),
            currency=settings.currency,
            rows=[row for _, row in ordered],
            no_match_case_numbers=no_match[:20],
        )
