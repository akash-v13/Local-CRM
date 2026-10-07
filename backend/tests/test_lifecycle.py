"""Unit tests for the case lifecycle rules (no database)."""

import pytest

from app.domain.errors import InvalidTransitionError
from app.domain.lifecycle import ALLOWED_TRANSITIONS, CaseStatus, ensure_transition_allowed

S = CaseStatus


def test_every_status_has_a_transition_entry() -> None:
    assert set(ALLOWED_TRANSITIONS) == set(CaseStatus)


def test_transitions_only_point_to_known_statuses() -> None:
    for targets in ALLOWED_TRANSITIONS.values():
        assert targets <= set(CaseStatus)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.INTAKE, S.QUEUED),
        (S.INTAKE, S.ENRICHMENT_FAILED),
        (S.QUEUED, S.ASSIGNED_AI),
        (S.ASSIGNED_AI, S.ASSIGNED_AGENT),  # AI hands off to a human
        (S.ASSIGNED_AI, S.QUEUED),  # automatic reply held: back to the queue
        (S.ASSIGNED_AGENT, S.QUEUED),  # manual reroute
        (S.WAITING_APPROVAL, S.ASSIGNED_AGENT),  # approver rejected
        (S.SOLVED, S.QUEUED),  # customer replied within the reopen window
        (S.SOLVED, S.CLOSED),
    ],
)
def test_allowed_transitions(current: CaseStatus, target: CaseStatus) -> None:
    ensure_transition_allowed(current, target)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.INTAKE, S.SOLVED),  # can't skip enrichment and handling
        (S.QUEUED, S.CLOSED),
        (S.CLOSED, S.QUEUED),  # closed is final; a reply creates a new linked case
        (S.ASSIGNED_AI, S.WAITING_ON_CUSTOMER),
    ],
)
def test_forbidden_transitions(current: CaseStatus, target: CaseStatus) -> None:
    with pytest.raises(InvalidTransitionError):
        ensure_transition_allowed(current, target)
