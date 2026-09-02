"""Explicit finite-state machine for RecoveryCase (STATE_MACHINES.md).

Transitions are validated here and enforced by case_service.transition in the
same DB transaction as the business write. Terminal states are immutable.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.db.enums import CaseStatus


@dataclass(frozen=True)
class Transition:
    frm: CaseStatus
    to: CaseStatus
    actor: str


# Authoritative transition table (STATE_MACHINES.md §2).
TRANSITIONS: set[Transition] = {
    Transition(CaseStatus.DETECTED, CaseStatus.ANALYZING, "worker"),
    Transition(CaseStatus.ANALYZING, CaseStatus.DIAGNOSED, "orchestrator"),
    Transition(CaseStatus.ANALYZING, CaseStatus.FAILED, "worker"),
    Transition(CaseStatus.DIAGNOSED, CaseStatus.PLANNED, "orchestrator"),
    Transition(CaseStatus.PLANNED, CaseStatus.POLICY_CHECK, "orchestrator"),
    Transition(CaseStatus.POLICY_CHECK, CaseStatus.APPROVED, "policy"),
    Transition(CaseStatus.POLICY_CHECK, CaseStatus.AWAITING_APPROVAL, "policy"),
    Transition(CaseStatus.POLICY_CHECK, CaseStatus.PLANNED, "orchestrator"),
    Transition(CaseStatus.POLICY_CHECK, CaseStatus.BLOCKED, "policy"),
    Transition(CaseStatus.AWAITING_APPROVAL, CaseStatus.APPROVED, "human"),
    Transition(CaseStatus.AWAITING_APPROVAL, CaseStatus.ESCALATED, "human"),
    Transition(CaseStatus.APPROVED, CaseStatus.EXECUTING, "executor"),
    Transition(CaseStatus.EXECUTING, CaseStatus.VERIFYING, "executor"),
    Transition(CaseStatus.EXECUTING, CaseStatus.AWAITING_APPROVAL, "executor"),
    Transition(CaseStatus.EXECUTING, CaseStatus.FAILED, "executor"),
    Transition(CaseStatus.VERIFYING, CaseStatus.RECOVERED, "verifier"),
    Transition(CaseStatus.VERIFYING, CaseStatus.CLOSED_UNRECOVERED, "scheduler"),
    # Recovery-ladder re-entry: attempt executed but not captured, budget remains.
    Transition(CaseStatus.VERIFYING, CaseStatus.DIAGNOSED, "orchestrator"),
}

# States from which a scheduler may transition to EXPIRED (age > TTL) or CANCELLED.
NON_TERMINAL = frozenset(
    {
        CaseStatus.DETECTED,
        CaseStatus.ANALYZING,
        CaseStatus.DIAGNOSED,
        CaseStatus.PLANNED,
        CaseStatus.POLICY_CHECK,
        CaseStatus.AWAITING_APPROVAL,
        CaseStatus.APPROVED,
        CaseStatus.EXECUTING,
        CaseStatus.VERIFYING,
    }
)

TERMINAL = frozenset(
    {
        CaseStatus.RECOVERED,
        CaseStatus.CLOSED_UNRECOVERED,
        CaseStatus.EXPIRED,
        CaseStatus.CANCELLED,
        CaseStatus.BLOCKED,
        CaseStatus.ESCALATED,
        CaseStatus.FAILED,
    }
)


_TRANSITION_PAIRS = {(t.frm, t.to) for t in TRANSITIONS}


def can_transition(frm: CaseStatus, to: CaseStatus) -> bool:
    if frm == to:
        return True
    if (frm, to) in _TRANSITION_PAIRS:
        return True
    # Scheduler transitions: any non-terminal -> EXPIRED / CANCELLED.
    if frm in NON_TERMINAL and to in (CaseStatus.EXPIRED, CaseStatus.CANCELLED):
        return True
    # Verifier truth: a captured payment is terminal reality from ANY active
    # state (self-heal: payment.captured webhook races the pipeline, S08).
    if frm in NON_TERMINAL and to is CaseStatus.RECOVERED:
        return True
    return False


def assert_transition(frm: CaseStatus, to: CaseStatus) -> None:
    if not can_transition(frm, to):
        raise ValueError(f"Illegal FSM transition: {frm.value} -> {to.value}")


def is_terminal(status: CaseStatus) -> bool:
    return status in TERMINAL


def is_active(status: CaseStatus) -> bool:
    return not is_terminal(status)
