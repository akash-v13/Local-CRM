"""Case lifecycle: the statuses a case can be in and the allowed moves between them.

This is the single source of truth for status changes (see Idea 7 in
docs/04-product-ideas.md). Nothing else in the codebase should decide whether
a transition is valid — call `ensure_transition_allowed` instead.

    Intake ──▶ Queued ──▶ AssignedAgent / AssignedAI ──▶ WaitingApproval ──▶ Solved ──▶ Closed
      │                         │                                              │
      └─▶ EnrichmentFailed      └─▶ WaitingOnCustomer ──▶ Queued               └─▶ Queued (reopen)

To add a transition: add it to `ALLOWED_TRANSITIONS`, then add a test in
tests/test_lifecycle.py.
"""

from enum import StrEnum

from app.domain.errors import InvalidTransitionError


class CaseStatus(StrEnum):
    INTAKE = "Intake"  # created; enrichment running
    ENRICHMENT_FAILED = "EnrichmentFailed"  # enrichment errored; needs a retry or a human
    QUEUED = "Queued"  # enriched and matched to a queue; waiting for a handler
    ASSIGNED_AGENT = "AssignedAgent"  # a human agent owns it
    ASSIGNED_AI = "AssignedAI"  # the AI agent is drafting / may auto-send
    WAITING_APPROVAL = "WaitingApproval"  # a reply or payout needs sign-off
    WAITING_ON_CUSTOMER = "WaitingOnCustomer"  # we asked the customer something; SLA paused
    SOLVED = "Solved"  # reply sent; customer can still reply until the reopen window ends
    CLOSED = "Closed"  # reopen window over; final


S = CaseStatus

ALLOWED_TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    S.INTAKE: frozenset({S.QUEUED, S.ENRICHMENT_FAILED}),
    S.ENRICHMENT_FAILED: frozenset({S.INTAKE}),
    S.QUEUED: frozenset({S.ASSIGNED_AGENT, S.ASSIGNED_AI}),
    # AssignedAI → Queued: an automatic reply was held, so the case goes back for a person.
    S.ASSIGNED_AI: frozenset({S.ASSIGNED_AGENT, S.WAITING_APPROVAL, S.SOLVED, S.QUEUED}),
    # AssignedAgent → Queued is a manual reroute to another queue.
    S.ASSIGNED_AGENT: frozenset({S.WAITING_APPROVAL, S.WAITING_ON_CUSTOMER, S.SOLVED, S.QUEUED}),
    S.WAITING_ON_CUSTOMER: frozenset({S.QUEUED}),
    # WaitingApproval → AssignedAgent means the approver rejected it (with a reason).
    S.WAITING_APPROVAL: frozenset({S.ASSIGNED_AGENT, S.SOLVED}),
    # Solved → Queued is a customer reply inside the reopen window.
    S.SOLVED: frozenset({S.QUEUED, S.CLOSED}),
    S.CLOSED: frozenset(),
}


# "Open" = still needs work. Solved cases may still reopen, but nobody owes a response.
OPEN_STATUSES: frozenset[CaseStatus] = frozenset(CaseStatus) - {S.SOLVED, S.CLOSED}


def ensure_transition_allowed(current: CaseStatus, target: CaseStatus) -> None:
    """Raise `InvalidTransitionError` if a case may not move from `current` to `target`."""
    if target not in ALLOWED_TRANSITIONS[current]:
        allowed = ", ".join(sorted(ALLOWED_TRANSITIONS[current])) or "none (final status)"
        raise InvalidTransitionError(
            f"Cannot move a case from {current} to {target}. Allowed from {current}: {allowed}."
        )
