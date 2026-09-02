"""Orchestration pipeline: drives a case DETECTED -> terminal (STATE_MACHINES §3).

The worker owns the ladder: re-diagnose after each failed attempt, walk
S1/S2 -> S3 -> S5 -> S6, fast-forward cooldowns/SLA timeouts in batch mode via a
virtual clock. Policy still gates every action; executors still own side effects.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.decide import CaseContext, decide_and_persist
from app.db.enums import (
    ActionStatus,
    Actor,
    CaseStatus,
    DecisionOrigin,
    DiagnosisClass,
    EscalationStatus,
    ExecutionMode,
    PaymentStatus,
)
from app.db.enums import ActionType as AT
from app.db.models import (
    AgentDecision,
    Payment,
    PolicyDecision,
    RecoveryAction,
    RecoveryCase,
)
from app.domain import diagnosis as dx
from app.domain import strategies as st
from app.domain.fsm import is_terminal
from app.executors.actions import ExecutorDeps, execute_for_strategy
from app.policy.config import PolicyConfig
from app.policy.engine import evaluate
from app.policy.rules import PolicyContext
from app.risk import engine as risk
from app.services import audit, case_service
from app.verification import service as verification

MAX_STEPS = 32

SLA_HOURS_BY_BAND = {"CRITICAL": 2, "HIGH": 6, "MEDIUM": 24, "LOW": 48}


class VirtualClock:
    """Batch-mode time source: deterministic, advances past cooldowns instantly."""

    def __init__(self, start: datetime):
        self._now = start

    def now(self) -> datetime:
        return self._now

    def advance_minutes(self, minutes: int) -> None:
        self._now += timedelta(minutes=minutes)


async def load_case_full(session: AsyncSession, case_id) -> RecoveryCase | None:
    row = await session.execute(
        select(RecoveryCase)
        .options(selectinload(RecoveryCase.payment), selectinload(RecoveryCase.customer))
        .where(RecoveryCase.id == case_id)
    )
    return row.scalar_one_or_none()


def _age_hours(clock: VirtualClock, payment: Payment) -> float:
    ref = payment.rzp_created_at or payment.created_at
    return max(0.0, (clock.now() - ref).total_seconds() / 3600.0)


def _has_token(case: RecoveryCase, customer) -> bool:
    """Token snapshot at failure time: ground_truth is authoritative for the
    simulator; the live path falls back to the customer row (token state can
    drift across cases when the dataset reuses a pooled customer)."""
    gt = case.ground_truth or {}
    gt_customer = gt.get("customer") or {}
    if "has_saved_token" in gt_customer:
        return bool(gt_customer["has_saved_token"])
    return bool(customer and customer.has_saved_token)


async def _notify_count(session: AsyncSession, case_id) -> int:
    """Customer contacts (one link/notify action = one contact, not per channel)."""
    n = await session.execute(
        select(func.count()).select_from(RecoveryAction).where(
            RecoveryAction.case_id == case_id,
            RecoveryAction.action_type.in_([AT.SEND_RECOVERY_LINK, AT.NOTIFY_CUSTOMER]),
        )
    )
    return int(n.scalar_one())


async def _retry_actions_used(session: AsyncSession, merchant_id) -> int:
    n = await session.execute(
        select(func.count())
        .select_from(RecoveryAction)
        .join(RecoveryCase, RecoveryAction.case_id == RecoveryCase.id)
        .where(RecoveryCase.merchant_id == merchant_id, RecoveryAction.action_type == AT.RETRY_CHARGE)
    )
    return int(n.scalar_one())


async def _latest_decision(session: AsyncSession, case_id) -> AgentDecision | None:
    row = await session.execute(
        select(AgentDecision).where(AgentDecision.case_id == case_id).order_by(AgentDecision.created_at.desc(), AgentDecision.id.desc()).limit(1)
    )
    return row.scalar_one_or_none()


async def _risk_enrich(session: AsyncSession, case: RecoveryCase, clock: VirtualClock) -> None:
    payment = case.payment
    customer = case.customer
    prior_dx, _ = dx.diagnose(payment.error_reason, payment.error_code, payment.error_source)
    score, band, comps = risk.compute_risk(
        amount_minor=payment.amount_minor,
        diagnosis=case.diagnosis_class or prior_dx,
        lifetime_value_minor=customer.lifetime_value_minor if customer else 0,
        tenure_days=customer.tenure_days if customer else 0,
        prior_recoveries_90d=customer.prior_recoveries_90d if customer else 0,
        retry_count=case.retry_count,
        age_hours=_age_hours(clock, payment),
    )
    case.risk_score = score
    case.risk_band = band
    case.sla_deadline_at = clock.now() + timedelta(hours=SLA_HOURS_BY_BAND[band.value])
    await session.flush()
    await audit.append_event(
        session,
        case_id=case.id,
        actor=Actor.SYSTEM,
        event_type="RISK_SCORED",
        detail={"score": score, "band": band.value, "components": {k: round(v, 2) for k, v in comps.__dict__.items()}},
    )


async def _persist_policy_decision(session, case, decision, result) -> PolicyDecision:
    pd = PolicyDecision(
        case_id=case.id,
        decision_id=decision.id if decision else None,
        proposed_action=(st.STRATEGY_CATALOG[decision.strategy_id]["action"] or "NONE")
        if decision
        else "NONE",
        verdict=result.verdict,
        rule_results={"hits": result.rule_results, "triggered": result.triggered_rule_id},
        config_snapshot=result.config_snapshot,
    )
    session.add(pd)
    await session.flush()
    await audit.append_event(
        session,
        case_id=case.id,
        actor=Actor.POLICY,
        event_type="POLICY_EVALUATED",
        detail={"verdict": result.verdict.value, "triggered_rule": result.triggered_rule_id},
    )
    return pd


def _build_policy_ctx(case, payment, decision, clock, cfg, contact_count, budget_used) -> PolicyContext:
    action = (st.STRATEGY_CATALOG[decision.strategy_id]["action"] or "NONE")
    return PolicyContext(
        case_status=case.status,
        payment_status=payment.status,
        captured_for_order=False,
        amount_minor=payment.amount_minor,
        retry_count=case.retry_count,
        last_attempt_at=case.last_attempt_at,
        diagnosis_class=case.diagnosis_class,
        diagnosis_confidence=float(decision.diagnosis_confidence),
        strategy_confidence=float(decision.strategy_confidence),
        contact_count_7d=contact_count,
        downtime_active=False,
        age_hours=_age_hours(clock, payment),
        simulation_budget_remaining=max(0, cfg.simulation_budget - budget_used),
        proposed_action=AT(action) if action != "NONE" else AT.CREATE_ESCALATION,
        proposed_delay_minutes=decision.params.get("delay_minutes"),
        link_amount_minor=None,
        channel=None,
        existing_action=False,
        config=cfg,
        now=clock.now(),
    )


async def _ensure_escalation(session: AsyncSession, case: RecoveryCase, reason: str, cfg: PolicyConfig) -> None:
    """Guarantee an escalation row exists whenever a case parks for a human."""
    from app.db.enums import EscalationReasonCode
    from app.db.models import Escalation

    rows = await session.execute(select(Escalation).where(Escalation.case_id == case.id))
    if rows.scalars().first() is not None:
        return
    payment = case.payment
    if payment.amount_minor >= cfg.approval_limit_minor:
        code = EscalationReasonCode.AMOUNT_CEILING
    elif case.diagnosis_class == DiagnosisClass.UNKNOWN:
        code = EscalationReasonCode.UNKNOWN_DIAGNOSIS
    elif (case.agent_confidence or 1.0) < cfg.confidence_floor:
        code = EscalationReasonCode.LOW_CONFIDENCE
    elif case.retry_count >= cfg.max_retries:
        code = EscalationReasonCode.MAX_RETRIES_EXHAUSTED
    else:
        code = EscalationReasonCode.LOW_CONFIDENCE
    esc = Escalation(
        escalation_ref=await case_service.next_ref(session, "escalation_ref", "ESC"),
        case_id=case.id,
        reason_code=code,
        note=reason,
    )
    session.add(esc)
    await session.flush()
    await audit.append_event(
        session, case_id=case.id, actor=Actor.SYSTEM, event_type="ESCALATION_CREATED",
        detail={"escalation_ref": esc.escalation_ref, "reason_code": code.value},
    )


async def _force_escalation_decision(session: AsyncSession, case: RecoveryCase, reason: str) -> AgentDecision:
    d = AgentDecision(
        case_id=case.id,
        decision_ref=await case_service.next_ref(session, "decision_ref", "DEC"),
        origin=DecisionOrigin.FALLBACK,
        diagnosis_class=case.diagnosis_class or DiagnosisClass.UNKNOWN,
        diagnosis_confidence=case.agent_confidence or 0.5,
        strategy_id=st.S5,
        strategy_confidence=0.9,
        params={},
        rationale=reason,
        reasoning_trace={"path": "ladder_escalation"},
        iterations_used=1,
    )
    session.add(d)
    await session.flush()
    case.strategy_id = st.S5
    await session.flush()
    await audit.append_event(
        session, case_id=case.id, actor=Actor.SYSTEM, event_type="LADDER_OVERRIDE",
        detail={"to": st.S5, "reason": reason},
    )
    return d


async def _step(session: AsyncSession, case: RecoveryCase, deps: ExecutorDeps, clock: VirtualClock) -> bool:
    """Advance one FSM step. Returns False when no forward move is possible."""
    payment = case.payment
    customer = case.customer
    cfg = deps.cfg

    if case.status == CaseStatus.DETECTED:
        await case_service.transition(session, case, CaseStatus.ANALYZING, actor=Actor.SYSTEM, reason="worker claimed")
        await _risk_enrich(session, case, clock)
        return True

    if case.status == CaseStatus.ANALYZING:
        ctx = CaseContext(
            age_hours=_age_hours(clock, payment),
            downtime_active=False,
            notify_count=await _notify_count(session, case.id),
            has_token=_has_token(case, customer),
        )
        await decide_and_persist(
            session, case, payment, customer, ctx, cfg, retry_count=case.retry_count
        )
        await case_service.transition(session, case, CaseStatus.DIAGNOSED, actor=Actor.SYSTEM)
        return True

    if case.status == CaseStatus.DIAGNOSED:
        # Retry-ladder re-entry: a retry already ran -> re-decide with the
        # updated budget so the agent escalates (S5) instead of retrying until
        # policy hard-blocks. (The notify ladder is handled in VERIFYING via
        # _force_escalation_decision; only retries consume retry_count.)
        if case.retry_count > 0:
            ctx = CaseContext(
                age_hours=_age_hours(clock, payment),
                downtime_active=False,
                notify_count=await _notify_count(session, case.id),
                has_token=_has_token(case, customer),
            )
            await decide_and_persist(
                session, case, payment, customer, ctx, cfg, retry_count=case.retry_count
            )
        await case_service.transition(session, case, CaseStatus.PLANNED, actor=Actor.SYSTEM)
        return True

    if case.status == CaseStatus.PLANNED:
        await case_service.transition(session, case, CaseStatus.POLICY_CHECK, actor=Actor.SYSTEM)
        return True

    if case.status == CaseStatus.POLICY_CHECK:
        decision = await _latest_decision(session, case.id)
        contact_count = await _notify_count(session, case.id)
        budget_used = await _retry_actions_used(session, case.merchant_id)
        ctxpol = _build_policy_ctx(case, payment, decision, clock, cfg, contact_count, budget_used)
        result = evaluate(ctxpol)
        await _persist_policy_decision(session, case, decision, result)

        if result.verdict.value == "ALLOW":
            await case_service.transition(session, case, CaseStatus.APPROVED, actor=Actor.POLICY)
            return True
        if result.verdict.value == "ESCALATE":
            await _ensure_escalation(session, case, f"policy escalate: {result.triggered_rule_id}", cfg)
            await case_service.transition(session, case, CaseStatus.AWAITING_APPROVAL, actor=Actor.POLICY, reason=result.triggered_rule_id or "")
            return True
        if result.verdict.value == "WAIT":
            if not deps.fast_forward:
                return False  # live mode: leave planned; worker re-claims after cooldown
            cd = cfg.cooldown_base_min * (2 ** case.retry_count)
            clock.advance_minutes(max(cd, 1))
            await case_service.transition(session, case, CaseStatus.PLANNED, actor=Actor.POLICY, reason=f"wait; fast-forwarded {cd}m")
            return True
        # BLOCK: swap in the deterministic fallback once; second block is terminal.
        if decision is not None and decision.origin == DecisionOrigin.LLM:
            ctx = CaseContext(
                age_hours=_age_hours(clock, payment),
                downtime_active=False,
                notify_count=contact_count,
                has_token=_has_token(case, customer),
            )
            await decide_and_persist(
                session, case, payment, customer, ctx, cfg, retry_count=case.retry_count
            )
            await case_service.transition(session, case, CaseStatus.PLANNED, actor=Actor.POLICY, reason=f"blocked by {result.triggered_rule_id}; fallback")
            return True
        await case_service.transition(session, case, CaseStatus.BLOCKED, actor=Actor.POLICY, reason=f"blocked by {result.triggered_rule_id}")
        await session.flush()
        return True

    if case.status == CaseStatus.APPROVED:
        decision = await _latest_decision(session, case.id)
        await case_service.transition(session, case, CaseStatus.EXECUTING, actor=Actor.EXECUTOR)
        action = await execute_for_strategy(session, case, decision, deps) if decision else None

        if decision is None or decision.strategy_id in (st.S6, st.S5):
            # S6 (no-op) and S5 (escalation) complete via verification/escalation.
            if decision is None or decision.strategy_id == st.S5:
                await case_service.transition(
                    session, case, CaseStatus.AWAITING_APPROVAL,
                    actor=Actor.EXECUTOR, reason="escalation created; awaiting human",
                )
            else:
                await case_service.transition(
                    session, case, CaseStatus.VERIFYING, actor=Actor.EXECUTOR, reason="no-op strategy",
                )
            return True
        if action is not None and action.status == ActionStatus.FAILED:
            await case_service.transition(session, case, CaseStatus.FAILED, actor=Actor.EXECUTOR, reason=action.error or "execution failed")
            return True
        if payment.status == PaymentStatus.CAPTURED:
            return True  # capture confirmed inside executor
        case.last_attempt_at = clock.now()
        await case_service.transition(session, case, CaseStatus.VERIFYING, actor=Actor.EXECUTOR)
        return True

    if case.status == CaseStatus.EXECUTING:
        await case_service.transition(session, case, CaseStatus.VERIFYING, actor=Actor.EXECUTOR)
        return True

    if case.status == CaseStatus.VERIFYING:
        if payment.status == PaymentStatus.CAPTURED:
            await verification.record_capture(
                session, case, payment, gateway_ref=None,
                mode=ExecutionMode.SIMULATED, source="verifier_poll",
            )
            return True

        decision = await _latest_decision(session, case.id)
        if decision is not None and decision.strategy_id == st.S6:
            await verification.close_unrecovered(session, case, reason="S6 stop: no further recovery value")
            return True

        notify_count = await _notify_count(session, case.id)
        # Ladder terminations:
        if case.diagnosis_class == DiagnosisClass.INSTRUMENT_INVALID and notify_count > 0:
            await verification.close_unrecovered(session, case, reason="invalid instrument; customer notified once (S4->S6)")
            return True
        if notify_count >= cfg.contact_cap_7d:
            await _force_escalation_decision(session, case, "contact cap reached; ladder escalates to human")
            await case_service.transition(session, case, CaseStatus.DIAGNOSED, actor=Actor.SYSTEM, reason="ladder re-entry")
            return True
        if not deps.fast_forward:
            return False  # live mode: wait for the cooldown before re-diagnosing
        # Cooldown elapses before the next attempt is even proposed.
        clock.advance_minutes(st.cooldown_minutes(case.retry_count))
        await case_service.transition(session, case, CaseStatus.DIAGNOSED, actor=Actor.SYSTEM, reason="attempt not captured; re-diagnose")
        return True

    if case.status == CaseStatus.AWAITING_APPROVAL:
        if not deps.fast_forward:
            return False  # live mode: a human decides
        # Batch: no human in the loop; 48h approval window fast-forwards to ESCALATED.
        clock.advance_minutes(48 * 60)
        await case_service.transition(session, case, CaseStatus.ESCALATED, actor=Actor.HUMAN, reason="approval window elapsed (batch)")
        await _expire_open_escalations(session, case)
        return True

    return False


def action_mode(case: RecoveryCase):
    from app.db.enums import ExecutionMode

    return ExecutionMode.SIMULATED


async def _expire_open_escalations(session: AsyncSession, case: RecoveryCase) -> None:
    from app.db.models import Escalation

    rows = await session.execute(select(Escalation).where(Escalation.case_id == case.id))
    for esc in rows.scalars():
        if esc.status == EscalationStatus.OPEN:
            esc.status = EscalationStatus.EXPIRED
            esc.decided_by = "timeout"
            esc.decision_note = "48h window elapsed (batch fast-forward)"
            from app.db.models import utcnow

            esc.decided_at = utcnow()
    await session.flush()


async def advance_case(session: AsyncSession, case: RecoveryCase, deps: ExecutorDeps, clock: VirtualClock) -> None:
    """Run a case to a terminal state (bounded by MAX_STEPS)."""
    steps = 0
    while not is_terminal(case.status) and steps < MAX_STEPS:
        steps += 1
        moved = await _step(session, case, deps, clock)
        if not moved:
            break
    if not is_terminal(case.status):
        await verification.close_unrecovered(session, case, reason="step budget exhausted")
