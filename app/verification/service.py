"""Verification: capture recording, self-heal, and honest outcome bookkeeping.

Capture is the only source of truth for RECOVERED. It can arrive as:
- an executor result (simulated retry/link captured),
- a payment.captured webhook (real link paid, or S08 self-heal racing the pipeline).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Actor, CaseOutcome, CaseStatus, ExecutionMode, PaymentStatus
from app.db.models import Payment, RecoveryCase
from app.services import audit, case_service


async def record_capture(
    session: AsyncSession,
    case: RecoveryCase,
    payment: Payment,
    *,
    gateway_ref: str | None,
    mode: ExecutionMode,
    source: str,
) -> None:
    """Mark payment captured + case RECOVERED (idempotent; audit-logged)."""
    if case.status == CaseStatus.RECOVERED:
        return

    payment.status = PaymentStatus.CAPTURED
    case.recovered_amount_minor = payment.amount_minor
    case.outcome = CaseOutcome.SELF_HEALED if source == "webhook_self_heal" else CaseOutcome.RECOVERED

    # Self-heal may arrive while the case is anywhere in the pipeline; the FSM
    # allows verifier RECOVERED from any non-terminal state.
    await case_service.transition(
        session, case, CaseStatus.RECOVERED, actor=Actor.VERIFIER,
        reason=f"capture observed via {source} ({mode.value})",
    )
    from app.db.models import utcnow

    case.closed_at = utcnow()
    await session.flush()
    await audit.append_event(
        session,
        case_id=case.id,
        actor=Actor.VERIFIER,
        event_type="CAPTURE_CONFIRMED",
        detail={
            "gateway_ref": gateway_ref,
            "mode": mode.value,
            "source": source,
            "recovered_amount_minor": payment.amount_minor,
        },
    )


async def close_unrecovered(
    session: AsyncSession, case: RecoveryCase, *, reason: str
) -> None:
    from app.db.models import utcnow

    if case.status == CaseStatus.CLOSED_UNRECOVERED:
        return
    case.outcome = CaseOutcome.UNRECOVERED
    await case_service.transition(
        session, case, CaseStatus.CLOSED_UNRECOVERED, actor=Actor.SYSTEM, reason=reason
    )
    case.closed_at = utcnow()
    await session.flush()
    await audit.append_event(
        session,
        case_id=case.id,
        actor=Actor.SYSTEM,
        event_type="CASE_CLOSED",
        detail={"outcome": CaseOutcome.UNRECOVERED.value, "reason": reason},
    )


async def find_case_by_rzp_payment(session: AsyncSession, rzp_payment_id: str) -> RecoveryCase | None:
    row = await session.execute(
        select(RecoveryCase).join(Payment, RecoveryCase.payment_id == Payment.id).where(
            Payment.rzp_payment_id == rzp_payment_id
        )
    )
    return row.scalar_one_or_none()
