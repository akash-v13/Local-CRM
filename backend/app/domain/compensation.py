"""Compensation matrix: what does this case get, and does a person need to approve it?

The design (Ideas 3 and 5 in docs/04-product-ideas.md):

- **Decision table:** active rules are checked in priority order (lower number
  first; ties broken by creation time). The FIRST rule whose conditions match
  decides. Conditions use the same fields and operators as queue routing
  (`app/domain/routing.py`), including enrichment data and the case's queue.
- **Outcome:** each rule says what the customer gets: a type (refund, credit, …)
  and an amount, either fixed or a percentage of a case field (e.g. 50% of the
  order total), optionally capped. A rule can also decide "no compensation".
- **Approval:** a decision is approved automatically unless something says a
  person must look at it:
    * the rule itself requires approval,
    * the amount is above the queue's approval threshold,
    * the customer was already compensated recently (repeat-claimant check),
    * the amount couldn't be worked out (the field it depends on is missing).
- **The matrix decides the money; the AI only writes the message.** Drafts
  mention compensation only once it's approved.

Everything here is pure Python (no database), so the same logic powers real
decisions, the rule editor's live test and the backtest.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.domain.routing import ConditionResult, evaluate_criteria, to_number

CompensationType = Literal["refund", "store_credit", "voucher", "replacement", "points", "none"]

TYPE_LABELS: dict[str, str] = {
    "refund": "Refund",
    "store_credit": "Store credit",
    "voucher": "Voucher",
    "replacement": "Replacement",
    "points": "Loyalty points",
    "none": "No compensation",
}
# Types that carry an amount (a replacement or "none" doesn't).
MONETARY: frozenset[str] = frozenset({"refund", "store_credit", "voucher", "points"})


@dataclass(frozen=True)
class RuleCandidate:
    """The parts of a rule the decision needs. Decoupled from the database model."""

    id: UUID | None  # None for an unsaved draft being tested
    name: str
    priority: int
    created_at: datetime
    criteria: dict[str, Any]
    outcome: dict[str, Any]


@dataclass(frozen=True)
class RuleEvaluation:
    rule: RuleCandidate
    matched: bool
    conditions: list[ConditionResult] = field(default_factory=list)


@dataclass(frozen=True)
class PastCompensation:
    """A compensation the customer already received (for the repeat-claimant check)."""

    case_number: int
    decided_at: datetime
    type: str
    amount: float | None


@dataclass(frozen=True)
class Settings:
    """Tenant-wide guardrails."""

    repeat_lookback_days: int = 90
    repeat_max_count: int = 1  # this many past compensations in the window → approval
    currency: str = "USD"


@dataclass(frozen=True)
class Decision:
    rule: RuleCandidate | None  # None = no rule matched
    type: str | None
    amount: float | None
    currency: str
    needs_approval: bool
    approval_reasons: list[str]
    amount_explanation: str
    label: str | None  # what the AI is told, e.g. "Refund of USD 50.00"
    evaluations: list[RuleEvaluation]
    history: list[PastCompensation]


def compute_amount(outcome: dict[str, Any], context: dict[str, Any]) -> tuple[float | None, str]:
    """The amount a rule gives for this case, and how it was worked out.

    Returns (None, reason) when it can't be computed (e.g. the field is missing).
    """
    if outcome.get("type") not in MONETARY:
        return None, "No amount for this type."
    cap = to_number(outcome.get("cap"))
    if outcome.get("amount_mode") == "percent":
        source = str(outcome.get("percent_of") or "")
        base = to_number(context.get(source))
        percent = to_number(outcome.get("percent")) or 0.0
        if base is None:
            return (
                None,
                f"{source} isn't available on this case, so the amount can't be worked out.",
            )
        amount = round(base * percent / 100, 2)
        explanation = f"{percent:g}% of {source} ({base:g}) = {amount:.2f}"
    else:
        amount = round(to_number(outcome.get("amount")) or 0.0, 2)
        explanation = f"Fixed amount {amount:.2f}"
    if cap is not None and amount > cap:
        explanation += f", capped at {cap:.2f}"
        amount = round(cap, 2)
    return amount, explanation


def describe(type_: str | None, amount: float | None, currency: str) -> str | None:
    """Plain words for the AI and the agent, e.g. "Refund of USD 50.00"."""
    if type_ is None or type_ == "none":
        return None
    label = TYPE_LABELS.get(type_, type_)
    if amount is None:
        return label
    if type_ == "points":
        return f"{label}: {amount:g} points"
    return f"{label} of {currency} {amount:.2f}"


def decide(
    rules: Sequence[RuleCandidate],
    context: dict[str, Any],
    *,
    history: Sequence[PastCompensation],
    settings: Settings,
    approval_threshold: float | None,
    now: datetime,
) -> Decision:
    """Check rules in priority order; the first match decides. Then apply guardrails."""
    ordered = sorted(rules, key=lambda r: (r.priority, r.created_at))
    evaluations: list[RuleEvaluation] = []
    winner: RuleCandidate | None = None
    for rule in ordered:
        matched, results = evaluate_criteria(rule.criteria, context)
        evaluations.append(RuleEvaluation(rule, matched, results))
        if matched and winner is None:
            winner = rule

    window = [
        h
        for h in history
        if (now - h.decided_at).total_seconds() <= settings.repeat_lookback_days * 86400
    ]
    if winner is None:
        return Decision(
            rule=None,
            type=None,
            amount=None,
            currency=settings.currency,
            needs_approval=False,
            approval_reasons=[],
            amount_explanation="No rule matched.",
            label=None,
            evaluations=evaluations,
            history=window,
        )

    outcome = winner.outcome
    type_ = str(outcome.get("type") or "none")
    currency = str(outcome.get("currency") or settings.currency)
    amount, explanation = compute_amount(outcome, context)

    reasons: list[str] = []
    if type_ != "none":
        if outcome.get("requires_approval"):
            reasons.append(f'Rule "{winner.name}" always needs approval.')
        if type_ in MONETARY and amount is None:
            reasons.append(explanation)
        if (
            amount is not None
            and approval_threshold is not None
            and type_ != "points"
            and amount > approval_threshold
        ):
            reasons.append(
                f"{amount:.2f} is above the queue's approval threshold ({approval_threshold:.2f})."
            )
        if len(window) >= settings.repeat_max_count:
            total = sum(h.amount or 0 for h in window)
            reasons.append(
                f"Repeat claim: compensated {len(window)} time(s) in the last "
                f"{settings.repeat_lookback_days} days (total {total:.2f})."
            )

    return Decision(
        rule=winner,
        type=type_,
        amount=amount,
        currency=currency,
        needs_approval=bool(reasons),
        approval_reasons=reasons,
        amount_explanation=explanation,
        label=describe(type_, amount, currency),
        evaluations=evaluations,
        history=window,
    )
