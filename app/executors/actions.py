"""Action executors: the ONLY place side effects leave the system.

Every executor:
1. inserts the RecoveryAction row (idempotency key + unique constraints) BEFORE
   any gateway call (audit-before-execute, P14),
2. performs at most one gateway/outbox effect, labeled with execution_mode,
3. records the result; capture confirmation flows through verification.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import (
    ActionStatus,
    ActionType,
    Actor,
    EscalationReasonCode,
    ExecutionMode,
    NotificationChannel,
    NotificationStatus,
)
from app.db.models import Customer, Escalation, Notification, Payment, RecoveryAction, RecoveryCase
from app.domain import strategies as st
from app.integrations.gateway import RetryChargeRequest
from app.integrations.razorpay import RazorpayAdapter
from app.integrations.simulated_gateway import DEFAULT_PROBABILITIES, SimulatedGatewayAdapter
from app.policy.config import PolicyConfig
from app.services import audit, case_service
from app.verification import service as verification


@dataclass(frozen=True)
class ExecutorDeps:
    simulated: SimulatedGatewayAdapter
    real: RazorpayAdapter | None
    cfg: PolicyConfig
    fast_forward: bool = True  # batch: cooldowns elapse instantly


def _capture_probability(case: RecoveryCase) -> float:
    gt = case.ground_truth or {}
    p = gt.get("simulated_capture_probability")
    if p is not None:
        return float(p)
    d = case.diagnosis_class.value if case.diagnosis_class else "UNKNOWN"
    return DEFAULT_PROBABILITIES.get(d, 0.0)


async def _next_attempt_no(session: AsyncSession, case_id, action_type: ActionType) -> int:
    n = await session.execute(
        select(func.count()).select_from(RecoveryAction).where(
            RecoveryAction.case_id == case_id, RecoveryAction.action_type == action_type
        )
    )
    return int(n.scalar_one()) + 1


async def _new_action(
    session: AsyncSession, case: RecoveryCase, action_type: ActionType, mode: ExecutionMode
) -> RecoveryAction:
    attempt_no = await _next_attempt_no(session, case.id, action_type)
    action = RecoveryAction(
        action_ref=await case_service.next_ref(session, "action_ref", "ACT"),
        case_id=case.id,
        action_type=action_type,
        attempt_no=attempt_no,
        idempotency_key=f"{case.id}:{action_type.value}:{attempt_no}",
        execution_mode=mode,
        status=ActionStatus.EXECUTING,
    )
    session.add(action)
    await session.flush()
    await audit.append_event(
        session,
        case_id=case.id,
        actor=Actor.EXECUTOR,
        event_type="ACTION_STARTED",
        detail={"action_ref": action.action_ref, "type": action_type.value, "mode": mode.value},
    )
    return action


async def _finish_action(session, action: RecoveryAction, *, ok: bool, result: dict, gateway_ref=None, error=None):
    action.status = ActionStatus.SUCCEEDED if ok else ActionStatus.FAILED
    action.result = result
    action.gateway_ref = gateway_ref
    action.error = error
    from app.db.models import utcnow

    action.executed_at = utcnow()
    await session.flush()
    await audit.append_event(
        session,
        case_id=action.case_id,
        actor=Actor.EXECUTOR,
        event_type="ACTION_FINISHED",
        detail={"action_ref": action.action_ref, "ok": ok, "result": result, "error": error},
    )


async def execute_retry_charge(
    session: AsyncSession, case: RecoveryCase, payment: Payment, customer: Customer | None, deps: ExecutorDeps
) -> RecoveryAction:
    """S1/S2 — token re-charge. No public retry API exists, so this is SIMULATED."""
    action = await _new_action(session, case, ActionType.RETRY_CHARGE, ExecutionMode.SIMULATED)
    req = RetryChargeRequest(
        payment_id=payment.rzp_payment_id,
        order_id=payment.rzp_order_id,
        customer_id=customer.rzp_customer_id if customer else None,
        amount_minor=payment.amount_minor,
        currency=payment.currency,
        method=payment.method,
        token_available=bool(customer and customer.has_saved_token),
        capture_probability=_capture_probability(case),
    )
    res = await deps.simulated.retry_charge(req)
    case.retry_count += 1
    await _finish_action(
        session, action,
        ok=True,  # the attempt executed; outcome is in result
        result={"captured": res.success, "status": res.status, "simulated": res.simulated},
        gateway_ref=res.gateway_ref,
        error=res.error_reason if not res.success else None,
    )
    if res.success:
        await verification.record_capture(
            session, case, payment, gateway_ref=res.gateway_ref,
            mode=ExecutionMode.SIMULATED, source="executor_retry",
        )
    return action


async def _queue_notifications(
    session: AsyncSession, case: RecoveryCase, payment: Payment, customer: Customer | None, action: RecoveryAction, purpose: str
) -> list[Notification]:
    """Outbox render + enqueue; no real provider wired -> SIMULATED_SENT."""
    amount_rs = payment.amount_minor / 100
    body = (
        f"Your payment of Rs {amount_rs:,.2f} failed. "
        + ("Please update your payment method. " if purpose == "update_method" else "")
        + "Complete it here: {link}"
    )
    out = []
    for channel in (NotificationChannel.SMS, NotificationChannel.EMAIL):
        n = Notification(
            case_id=case.id,
            action_id=action.id,
            channel=channel,
            rendered_subject=f"Payment recovery ({case.case_ref})",
            rendered_body=body,
            status=NotificationStatus.SIMULATED_SENT,
        )
        session.add(n)
        out.append(n)
    await session.flush()
    await audit.append_event(
        session,
        case_id=case.id,
        actor=Actor.EXECUTOR,
        event_type="NOTIFICATIONS_QUEUED",
        detail={"action_ref": action.action_ref, "purpose": purpose, "count": len(out)},
    )
    return out


async def execute_send_link(
    session: AsyncSession, case: RecoveryCase, payment: Payment, customer: Customer | None, deps: ExecutorDeps
) -> RecoveryAction:
    """S3/S4 — payment link via Razorpay (REAL when keys configured) + outbox notify."""
    real = deps.real
    mode = ExecutionMode.REAL_RZP if real is not None else ExecutionMode.SIMULATED
    action = await _new_action(session, case, ActionType.SEND_RECOVERY_LINK, mode)
    purpose = "update_method" if case.diagnosis_class and case.diagnosis_class.value == "INSTRUMENT_INVALID" else "recover"

    if real is not None:
        res = await real.create_payment_link(
            amount_minor=payment.amount_minor,
            currency=payment.currency,
            customer_name=customer.masked_name if customer else "Customer",
            contact=None,
            email=customer.email_masked if customer else None,
            reference_id=case.case_ref,
        )
    else:
        res = await deps.simulated.create_payment_link(
            amount_minor=payment.amount_minor,
            currency=payment.currency,
            customer_name=customer.masked_name if customer else "Customer",
            contact=None,
            email=customer.email_masked if customer else None,
            reference_id=case.case_ref,
        )

    if not res.success:
        await _finish_action(session, action, ok=False, result={}, error=res.error)
        return action

    await _queue_notifications(session, case, payment, customer, action, purpose)
    await _finish_action(
        session, action, ok=True,
        result={"link_id": res.link_id, "short_url": res.short_url, "simulated": res.simulated},
        gateway_ref=res.link_id,
    )

    if real is None:
        # Fast-forward: would the customer pay this link within TTL?
        paid = await deps.simulated.simulate_link_payment(payment.rzp_payment_id, _capture_probability(case))
        if paid.success:
            await verification.record_capture(
                session, case, payment, gateway_ref=paid.gateway_ref,
                mode=ExecutionMode.SIMULATED, source="executor_link",
            )
    return action


def _escalation_reason(diagnosis, confidence, amount_minor, retry_count, cfg: PolicyConfig) -> EscalationReasonCode:
    if amount_minor >= cfg.approval_limit_minor:
        return EscalationReasonCode.AMOUNT_CEILING
    if diagnosis is not None and diagnosis.value == "UNKNOWN":
        return EscalationReasonCode.UNKNOWN_DIAGNOSIS
    if confidence is not None and confidence < cfg.confidence_floor:
        return EscalationReasonCode.LOW_CONFIDENCE
    if retry_count >= cfg.max_retries:
        return EscalationReasonCode.MAX_RETRIES_EXHAUSTED
    return EscalationReasonCode.LOW_CONFIDENCE


async def execute_escalation(
    session: AsyncSession, case: RecoveryCase, payment: Payment, deps: ExecutorDeps, reason: str
) -> RecoveryAction:
    action = await _new_action(session, case, ActionType.CREATE_ESCALATION, ExecutionMode.OUTBOX)
    code = _escalation_reason(
        case.diagnosis_class, case.agent_confidence, payment.amount_minor, case.retry_count, deps.cfg
    )
    esc = Escalation(
        escalation_ref=await case_service.next_ref(session, "escalation_ref", "ESC"),
        case_id=case.id,
        reason_code=code,
        note=reason,
    )
    session.add(esc)
    await session.flush()
    await _finish_action(
        session, action, ok=True,
        result={"escalation_ref": esc.escalation_ref, "reason_code": code.value},
    )
    return action


async def execute_for_strategy(
    session: AsyncSession, case: RecoveryCase, decision, deps: ExecutorDeps
) -> RecoveryAction | None:
    """Dispatch on strategy_id. Returns None for S6 (no side effect)."""
    payment = case.payment
    customer = case.customer
    strategy = decision.strategy_id

    if strategy == st.S6:
        return None
    if strategy == st.S5:
        return await execute_escalation(session, case, payment, deps, decision.rationale)
    if strategy in (st.S1, st.S2):
        return await execute_retry_charge(session, case, payment, customer, deps)
    if strategy in (st.S3, st.S4):
        return await execute_send_link(session, case, payment, customer, deps)
    raise ValueError(f"Unknown strategy {strategy}")
