"""FSM transition legality (STATE_MACHINES.md) — pure, no DB."""

import pytest

from app.db.enums import CaseStatus
from app.domain.fsm import assert_transition, can_transition, is_terminal


def test_happy_path():
    path = [
        (CaseStatus.DETECTED, CaseStatus.ANALYZING),
        (CaseStatus.ANALYZING, CaseStatus.DIAGNOSED),
        (CaseStatus.DIAGNOSED, CaseStatus.PLANNED),
        (CaseStatus.PLANNED, CaseStatus.POLICY_CHECK),
        (CaseStatus.POLICY_CHECK, CaseStatus.APPROVED),
        (CaseStatus.APPROVED, CaseStatus.EXECUTING),
        (CaseStatus.EXECUTING, CaseStatus.VERIFYING),
        (CaseStatus.VERIFYING, CaseStatus.RECOVERED),
    ]
    for frm, to in path:
        assert_transition(frm, to)


def test_ladder_reentry():
    assert can_transition(CaseStatus.VERIFYING, CaseStatus.DIAGNOSED)


def test_self_heal_from_any_active_state():
    for s in (CaseStatus.DETECTED, CaseStatus.ANALYZING, CaseStatus.DIAGNOSED,
              CaseStatus.PLANNED, CaseStatus.EXECUTING, CaseStatus.VERIFYING):
        assert can_transition(s, CaseStatus.RECOVERED)


def test_escalation_paths():
    assert can_transition(CaseStatus.POLICY_CHECK, CaseStatus.AWAITING_APPROVAL)
    assert can_transition(CaseStatus.EXECUTING, CaseStatus.AWAITING_APPROVAL)
    assert can_transition(CaseStatus.AWAITING_APPROVAL, CaseStatus.APPROVED)
    assert can_transition(CaseStatus.AWAITING_APPROVAL, CaseStatus.ESCALATED)


def test_illegal_transitions():
    with pytest.raises(ValueError):
        assert_transition(CaseStatus.RECOVERED, CaseStatus.DIAGNOSED)  # terminal is immutable
    with pytest.raises(ValueError):
        assert_transition(CaseStatus.BLOCKED, CaseStatus.PLANNED)


def test_terminal_immutable():
    for s in (CaseStatus.RECOVERED, CaseStatus.CLOSED_UNRECOVERED, CaseStatus.ESCALATED,
              CaseStatus.BLOCKED, CaseStatus.EXPIRED, CaseStatus.CANCELLED, CaseStatus.FAILED):
        assert is_terminal(s)
        with pytest.raises(ValueError):
            assert_transition(s, CaseStatus.PLANNED)
