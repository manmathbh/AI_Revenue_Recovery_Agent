"""Recoup API: webhook ingestion, case/dash read models, human decisions, eval.

Mount: uvicorn app.main:app. PII never leaves the DB layer (masked fields only).
"""

from __future__ import annotations

import hashlib
import hmac
import json

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import desc, func, select

from app.config import get_settings
from app.db.enums import ACTIVE_CASE_STATUSES, Actor, CaseStatus, EscalationStatus
from app.db.models import (
    AgentDecision,
    AuditEvent,
    Escalation,
    EvalRun,
    Notification,
    Payment,
    PolicyDecision,
    RecoveryAction,
    RecoveryCase,
)
from app.db.session import get_session, session_scope
from app.services.ingest import ingest_event

app = FastAPI(title="Recoup — AI Revenue Recovery Agent", version="0.1.0")


def _admin(x_admin_key: str | None) -> None:
    if x_admin_key != get_settings().admin_api_key:
        raise HTTPException(status_code=401, detail="invalid admin key")


def _verify_signature(raw: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    secret = get_settings().razorpay_webhook_secret.encode()
    expected = hmac.new(secret, raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.get("/", include_in_schema=False)
async def root():
    """Redirect to API documentation."""
    return RedirectResponse(url="/docs")


@app.get("/healthz")
@app.get("/health")
async def healthz():
    return {"ok": True}


@app.post("/webhooks/razorpay")
async def razorpay_webhook(request: Request, x_razorpay_signature: str | None = Header(default=None)):
    raw = await request.body()
    valid = _verify_signature(raw, x_razorpay_signature)
    try:
        event = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid json") from None
    async with session_scope() as session:
        res = await ingest_event(session, event, signature_valid=valid)
    # Always 200 for accepted deliveries (dedupe makes replays safe).
    return {"event_id": res.event_id, "duplicated": res.duplicated, "processed": res.processed}


@app.get("/api/dashboard")
async def dashboard(session=Depends(get_session)):
    status_rows = (
        await session.execute(select(RecoveryCase.status, func.count().label("n")).group_by(RecoveryCase.status))
    ).all()
    by_status = {s.value if hasattr(s, "value") else s: n for s, n in status_rows}
    recovered_minor = (
        await session.execute(select(func.coalesce(func.sum(RecoveryCase.recovered_amount_minor), 0)))
    ).scalar_one()
    active = (
        await session.execute(
            select(func.count()).select_from(RecoveryCase).where(RecoveryCase.status.in_(list(ACTIVE_CASE_STATUSES)))
        )
    ).scalar_one()
    return {
        "cases_by_status": by_status,
        "active_cases": int(active),
        "recovered_amount_inr": round(recovered_minor / 100, 2),
        "recovered_cases": by_status.get("RECOVERED", 0),
        "escalated_cases": by_status.get("ESCALATED", 0),
        "awaiting_approval": by_status.get("AWAITING_APPROVAL", 0),
    }


@app.get("/api/cases")
async def list_cases(status: str | None = None, limit: int = 50, session=Depends(get_session)):
    q = select(RecoveryCase).order_by(desc(RecoveryCase.created_at)).limit(min(limit, 200))
    if status:
        q = q.where(RecoveryCase.status == status)
    rows = (await session.execute(q)).scalars().all()
    return [
        {
            "case_ref": c.case_ref,
            "status": c.status.value,
            "risk_band": c.risk_band.value if c.risk_band else None,
            "risk_score": c.risk_score,
            "diagnosis": c.diagnosis_class.value if c.diagnosis_class else None,
            "strategy": c.strategy_id,
            "retry_count": c.retry_count,
            "amount_inr": None,
            "outcome": c.outcome.value if c.outcome else None,
            "created_at": c.created_at.isoformat(),
        }
        for c in rows
    ]


@app.get("/api/cases/{case_ref}")
async def case_detail(case_ref: str, session=Depends(get_session)):
    row = await session.execute(select(RecoveryCase).where(RecoveryCase.case_ref == case_ref))
    case = row.scalar_one_or_none()
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    payment = await session.get(Payment, case.payment_id)
    decisions = (
        await session.execute(
            select(AgentDecision).where(AgentDecision.case_id == case.id).order_by(AgentDecision.created_at)
        )
    ).scalars().all()
    policies = (
        await session.execute(
            select(PolicyDecision).where(PolicyDecision.case_id == case.id).order_by(PolicyDecision.created_at)
        )
    ).scalars().all()
    actions = (
        await session.execute(
            select(RecoveryAction).where(RecoveryAction.case_id == case.id).order_by(RecoveryAction.created_at)
        )
    ).scalars().all()
    notes = (
        await session.execute(
            select(Notification).where(Notification.case_id == case.id).order_by(Notification.created_at)
        )
    ).scalars().all()
    escalations = (
        await session.execute(
            select(Escalation).where(Escalation.case_id == case.id).order_by(Escalation.created_at)
        )
    ).scalars().all()
    audit_events = (
        await session.execute(
            select(AuditEvent).where(AuditEvent.case_id == case.id).order_by(AuditEvent.created_at, AuditEvent.id)
        )
    ).scalars().all()
    return {
        "case": {
            "case_ref": case.case_ref,
            "status": case.status.value,
            "risk_band": case.risk_band.value if case.risk_band else None,
            "risk_score": case.risk_score,
            "diagnosis": case.diagnosis_class.value if case.diagnosis_class else None,
            "strategy": case.strategy_id,
            "agent_confidence": float(case.agent_confidence) if case.agent_confidence is not None else None,
            "retry_count": case.retry_count,
            "outcome": case.outcome.value if case.outcome else None,
            "recovered_amount_inr": case.recovered_amount_minor / 100,
            "sla_deadline_at": case.sla_deadline_at.isoformat() if case.sla_deadline_at else None,
            "created_at": case.created_at.isoformat(),
        },
        "payment": {
            "rzp_payment_id": payment.rzp_payment_id,
            "status": payment.status.value,
            "amount_inr": payment.amount_minor / 100,
            "method": payment.method,
            "error_code": payment.error_code,
            "error_reason": payment.error_reason,
            "is_simulated": payment.is_simulated,
        },
        "decisions": [
            {
                "ref": d.decision_ref, "origin": d.origin.value, "model": d.model,
                "diagnosis": d.diagnosis_class.value, "strategy": d.strategy_id,
                "confidence": float(d.diagnosis_confidence), "rationale": d.rationale,
            }
            for d in decisions
        ],
        "policy": [
            {"verdict": p.verdict.value, "proposed": p.proposed_action, "rules": p.rule_results}
            for p in policies
        ],
        "actions": [
            {
                "ref": a.action_ref, "type": a.action_type.value, "attempt": a.attempt_no,
                "mode": a.execution_mode.value, "status": a.status.value,
                "gateway_ref": a.gateway_ref, "result": a.result, "executed_at": a.executed_at.isoformat() if a.executed_at else None,
            }
            for a in actions
        ],
        "notifications": [
            {"channel": n.channel.value, "status": n.status.value, "body": n.rendered_body} for n in notes
        ],
        "escalations": [
            {"ref": e.escalation_ref, "reason": e.reason_code.value, "status": e.status.value, "note": e.note}
            for e in escalations
        ],
        "audit": [
            {
                "at": e.created_at.isoformat(), "actor": e.actor.value, "type": e.event_type,
                "detail": e.detail, "hash": e.event_hash, "prev": e.prev_event_hash,
            }
            for e in audit_events
        ],
    }


@app.post("/api/escalations/{escalation_ref}/decision")
async def decide_escalation(
    escalation_ref: str,
    body: dict,
    x_admin_key: str | None = Header(default=None),
    session=Depends(get_session),
):
    _admin(x_admin_key)
    approve = body.get("approve")
    if approve not in (True, False):
        raise HTTPException(status_code=422, detail="approve must be true/false")
    row = await session.execute(select(Escalation).where(Escalation.escalation_ref == escalation_ref))
    esc = row.scalar_one_or_none()
    if esc is None:
        raise HTTPException(status_code=404, detail="escalation not found")
    case = await session.get(RecoveryCase, esc.case_id)
    from app.db.models import utcnow
    from app.services import case_service

    async with session.begin_nested():
        esc.status = EscalationStatus.APPROVED if approve else EscalationStatus.REJECTED
        esc.decided_by = "human"
        esc.decision_note = body.get("note", "")
        esc.decided_at = utcnow()
        if approve:
            await case_service.transition(
                session, case, CaseStatus.APPROVED, actor=Actor.HUMAN, reason="human approved"
            )
        else:
            await case_service.transition(
                session, case, CaseStatus.ESCALATED, actor=Actor.HUMAN, reason="human rejected"
            )
    await session.commit()
    return {"escalation_ref": esc.escalation_ref, "status": esc.status.value}


@app.get("/api/eval/report")
async def eval_report(session=Depends(get_session)):
    row = await session.execute(select(EvalRun).order_by(desc(EvalRun.started_at)).limit(1))
    run = row.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="no eval runs")
    return {"run_ref": run.run_ref, "seed": run.dataset_seed, "report": run.report}


def run():
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000)
