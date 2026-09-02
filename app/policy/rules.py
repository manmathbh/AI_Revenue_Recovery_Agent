"""Policy rule catalog P01–P14 (GUARDRAILS.md §2).

Each rule is a pure function of the PolicyContext. Ordered evaluation, short-circuit
on first hard-fail, full trace recorded even for skipped rules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.db.enums import ActionType, CaseStatus, DiagnosisClass, PaymentStatus
from app.policy.config import PolicyConfig

ELIGIBLE_STATES = frozenset(
    {
        CaseStatus.DIAGNOSED,
        CaseStatus.PLANNED,
        CaseStatus.POLICY_CHECK,
        CaseStatus.APPROVED,
        CaseStatus.AWAITING_APPROVAL,
    }
)

# Retry-type actions (subject to P03/P04/P09).
RETRY_ACTIONS = frozenset({ActionType.RETRY_CHARGE})

# Contact-type actions (subject to P08).
CONTACT_ACTIONS = frozenset(
    {ActionType.SEND_RECOVERY_LINK, ActionType.NOTIFY_CUSTOMER}
)

# Diagnosis classes for which an automated retry is NEVER permitted (P10).
RETRY_FORBIDDEN_DIAGNOSES = frozenset(
    {DiagnosisClass.INSTRUMENT_INVALID, DiagnosisClass.DUPLICATE_SELF_HEALED}
)


@dataclass(frozen=True)
class PolicyContext:
    case_status: CaseStatus
    payment_status: PaymentStatus
    captured_for_order: bool
    amount_minor: int
    retry_count: int
    last_attempt_at: datetime | None
    diagnosis_class: DiagnosisClass | None
    diagnosis_confidence: float
    strategy_confidence: float
    contact_count_7d: int
    downtime_active: bool
    age_hours: float
    simulation_budget_remaining: int
    proposed_action: ActionType
    proposed_delay_minutes: int | None
    link_amount_minor: int | None
    channel: str | None
    existing_action: bool
    config: PolicyConfig
    now: datetime


@dataclass(frozen=True)
class RuleHit:
    rule_id: str
    passed: bool
    reason: str
    evaluated: bool = True


@dataclass(frozen=True)
class RuleOutcome:
    hits: list[RuleHit] = field(default_factory=list)
    verdict_rule_id: str | None = None
    verdict: str | None = None


def _cooldown_minutes(config: PolicyConfig, attempt_no: int) -> int:
    raw = config.cooldown_base_min * (2 ** attempt_no)
    return max(config.cooldown_base_min, min(raw, 24 * 60))


def _rule(rule_id: str, passed: bool, reason: str) -> RuleHit:
    return RuleHit(rule_id, passed, reason)


def p01_state_eligible(ctx: PolicyContext) -> RuleHit:
    ok = ctx.case_status in ELIGIBLE_STATES and ctx.payment_status == PaymentStatus.FAILED
    return _rule("P01", ok, "case/state eligible" if ok else "case not in eligible state or payment not failed")


def p02_already_recovered(ctx: PolicyContext) -> RuleHit:
    already = ctx.payment_status == PaymentStatus.CAPTURED or ctx.captured_for_order
    return _rule("P02", not already, "not already recovered" if not already else "already recovered")


def p03_max_retries(ctx: PolicyContext) -> RuleHit:
    if ctx.proposed_action not in RETRY_ACTIONS:
        return _rule("P03", True, "not a retry action")
    ok = ctx.retry_count < ctx.config.max_retries
    return _rule("P03", ok, f"retry budget available ({ctx.retry_count}/{ctx.config.max_retries})" if ok else "max retries exhausted")


def p04_cooldown(ctx: PolicyContext) -> RuleHit:
    if ctx.proposed_action not in RETRY_ACTIONS or ctx.last_attempt_at is None:
        return _rule("P04", True, "no cooldown required")
    cd_min = _cooldown_minutes(ctx.config, ctx.retry_count)
    elapsed_min = (ctx.now - ctx.last_attempt_at).total_seconds() / 60.0
    ok = elapsed_min >= cd_min
    return _rule("P04", ok, f"cooldown {elapsed_min:.0f}/{cd_min}m elapsed" if ok else f"cooldown active ({cd_min}m)")


def p05_amount_ceiling(ctx: PolicyContext) -> RuleHit:
    if ctx.proposed_action == ActionType.CREATE_ESCALATION:
        return _rule("P05", True, "escalation always permitted")
    ok = ctx.amount_minor <= ctx.config.approval_limit_minor
    return _rule("P05", ok, "amount within auto-approval ceiling" if ok else "amount above auto-approval ceiling")


def p06_confidence_floor(ctx: PolicyContext) -> RuleHit:
    if ctx.proposed_action == ActionType.CREATE_ESCALATION:
        return _rule("P06", True, "escalation always permitted")
    floor = ctx.config.confidence_floor
    low = min(ctx.diagnosis_confidence, ctx.strategy_confidence)
    ok = low >= floor
    return _rule("P06", ok, f"confidence {low:.2f} >= floor {floor:.2f}" if ok else f"confidence {low:.2f} below floor {floor:.2f}")


def p07_duplicate_action(ctx: PolicyContext) -> RuleHit:
    ok = not ctx.existing_action
    return _rule("P07", ok, "no duplicate action" if ok else "duplicate action exists")


def p08_contact_cap(ctx: PolicyContext) -> RuleHit:
    if ctx.proposed_action not in CONTACT_ACTIONS:
        return _rule("P08", True, "not a contact action")
    ok = ctx.contact_count_7d < ctx.config.contact_cap_7d
    return _rule("P08", ok, f"contact budget ok ({ctx.contact_count_7d}/{ctx.config.contact_cap_7d})" if ok else "contact cap reached")


def p09_downtime_hold(ctx: PolicyContext) -> RuleHit:
    if ctx.proposed_action not in RETRY_ACTIONS or not ctx.downtime_active:
        return _rule("P09", True, "no downtime hold")
    return _rule("P09", False, "downtime active; hold retry until resolved")


def p10_diagnosis_action_compat(ctx: PolicyContext) -> RuleHit:
    if ctx.proposed_action in RETRY_ACTIONS and ctx.diagnosis_class in RETRY_FORBIDDEN_DIAGNOSES:
        return _rule("P10", False, f"retry forbidden for diagnosis {ctx.diagnosis_class.value}")
    return _rule("P10", True, "strategy compatible with diagnosis")


def p11_ttl(ctx: PolicyContext) -> RuleHit:
    ttl_h = ctx.config.ttl_hours
    ok = ctx.age_hours < ttl_h
    return _rule("P11", ok, f"within TTL ({ctx.age_hours:.0f}/{ttl_h}h)" if ok else "TTL expired")


def p12_simulation_budget(ctx: PolicyContext) -> RuleHit:
    if ctx.proposed_action not in RETRY_ACTIONS:
        return _rule("P12", True, "not a simulated charge")
    ok = ctx.simulation_budget_remaining > 0
    return _rule("P12", ok, "simulation budget available" if ok else "simulation budget exhausted")


def p13_param_sanity(ctx: PolicyContext) -> RuleHit:
    if ctx.proposed_delay_minutes is not None:
        if not (15 <= ctx.proposed_delay_minutes <= 72 * 60):
            return _rule("P13", False, "delay out of bounds [15m, 72h]")
    if ctx.link_amount_minor is not None and ctx.link_amount_minor != ctx.amount_minor:
        return _rule("P13", False, "link amount != original amount")
    if ctx.channel is not None and ctx.channel not in ("sms", "email"):
        return _rule("P13", False, "invalid channel")
    return _rule("P13", True, "parameters sane")


def p14_audit_write(ctx: PolicyContext) -> RuleHit:
    # Audit-before-execute is enforced structurally in the executor (decision +
    # policy rows are committed before any gateway call). This pure rule always
    # passes; it exists so the trace records P14 explicitly.
    return _rule("P14", True, "audit write will precede execution")


RULE_ORDER: list[tuple[str, object]] = [
    ("P01", p01_state_eligible),
    ("P02", p02_already_recovered),
    ("P03", p03_max_retries),
    ("P04", p04_cooldown),
    ("P05", p05_amount_ceiling),
    ("P06", p06_confidence_floor),
    ("P07", p07_duplicate_action),
    ("P08", p08_contact_cap),
    ("P09", p09_downtime_hold),
    ("P10", p10_diagnosis_action_compat),
    ("P11", p11_ttl),
    ("P12", p12_simulation_budget),
    ("P13", p13_param_sanity),
    ("P14", p14_audit_write),
]
