"""Case service: creation, FSM-guarded transitions, and ref minting."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Actor, CaseStatus
from app.db.models import Counter, RecoveryCase
from app.domain.fsm import assert_transition
from app.services import audit


async def next_ref(session: AsyncSession, kind: str, prefix: str) -> str:
    """Atomically mint the next human-readable ref (e.g. RC-000123)."""
    c = await session.get(Counter, kind)
    if c is None:
        c = Counter(name=kind, value=0)
        session.add(c)
        await session.flush()
    c.value += 1
    await session.flush()
    return f"{prefix}-{c.value:06d}"


async def create_case(
    session: AsyncSession,
    *,
    merchant_id: uuid.UUID,
    payment_id: uuid.UUID,
    customer_id: uuid.UUID | None,
    sla_deadline_at: datetime | None = None,
    ground_truth: dict | None = None,
) -> RecoveryCase:
    case_ref = await next_ref(session, "case_ref", "RC")
    case = RecoveryCase(
        case_ref=case_ref,
        merchant_id=merchant_id,
        payment_id=payment_id,
        customer_id=customer_id,
        status=CaseStatus.DETECTED,
        sla_deadline_at=sla_deadline_at,
        ground_truth=ground_truth,
    )
    session.add(case)
    await session.flush()
    await audit.append_event(
        session,
        case_id=case.id,
        actor=Actor.SYSTEM,
        event_type="CASE_CREATED",
        detail={"case_ref": case_ref, "status": CaseStatus.DETECTED.value},
    )
    return case


async def transition(
    session: AsyncSession,
    case: RecoveryCase,
    to: CaseStatus,
    *,
    actor: Actor,
    reason: str = "",
) -> None:
    frm = case.status
    assert_transition(frm, to)
    case.status = to
    await session.flush()
    await audit.append_event(
        session,
        case_id=case.id,
        actor=actor,
        event_type="STATE_TRANSITION",
        detail={"from": frm.value, "to": to.value, "reason": reason},
    )


async def get_case_by_ref(session: AsyncSession, case_ref: str) -> RecoveryCase | None:
    row = await session.execute(select(RecoveryCase).where(RecoveryCase.case_ref == case_ref))
    return row.scalar_one_or_none()


async def get_case_by_payment(session: AsyncSession, payment_id: uuid.UUID) -> RecoveryCase | None:
    row = await session.execute(
        select(RecoveryCase).where(RecoveryCase.payment_id == payment_id)
    )
    return row.scalar_one_or_none()


async def set_diagnosis(
    session: AsyncSession,
    case: RecoveryCase,
    *,
    diagnosis_class,
    strategy_id: str,
    confidence: float,
) -> None:
    case.diagnosis_class = diagnosis_class
    case.strategy_id = strategy_id
    case.agent_confidence = confidence
    await session.flush()


async def claim_next_case(
    session: AsyncSession,
    *,
    from_statuses: list[CaseStatus],
) -> RecoveryCase | None:
    """Claim one active case with SKIP LOCKED (single worker safe)."""
    stmt = (
        select(RecoveryCase)
        .where(RecoveryCase.status.in_(from_statuses))
        .order_by(RecoveryCase.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    row = await session.execute(stmt)
    return row.scalar_one_or_none()
