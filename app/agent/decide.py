"""Agent decision engine (AGENT_DESIGN.md).

Pattern: LLM proposes (diagnosis, strategy, confidence) -> deterministic
validation -> policy disposes. Any LLM failure, invalid output, or missing API
key falls back to the deterministic table (domain/diagnosis + domain/strategies).
Every decision row records its origin (LLM | FALLBACK) for honest eval.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.enums import Actor, DecisionOrigin, DiagnosisClass
from app.db.models import AgentDecision, Customer, Payment, RecoveryCase
from app.domain import diagnosis as dx
from app.domain import strategies as st
from app.policy.config import PolicyConfig
from app.services import audit, case_service

MAX_LLM_ATTEMPTS = 2


@dataclass(frozen=True)
class CaseContext:
    """Everything the agent is allowed to see (PII-masked)."""

    age_hours: float
    downtime_active: bool
    notify_count: int
    has_token: bool


def _fallback_decision(
    payment: Payment, ctx: CaseContext, cfg: PolicyConfig, retry_count: int
) -> AgentDecision:
    d, d_conf = dx.diagnose(payment.error_reason, payment.error_code, payment.error_source)
    choice = st.select_strategy(
        diagnosis=d,
        retry_count=retry_count,
        has_token=ctx.has_token,
        amount_minor=payment.amount_minor,
        confidence=d_conf,
        age_hours=ctx.age_hours,
        downtime_active=ctx.downtime_active,
        approval_limit_minor=cfg.approval_limit_minor,
        confidence_floor=cfg.confidence_floor,
    )
    return AgentDecision(
        origin=DecisionOrigin.FALLBACK,
        model=None,
        diagnosis_class=d,
        diagnosis_confidence=d_conf,
        strategy_id=choice.strategy_id,
        strategy_confidence=choice.confidence,
        params=choice.params,
        rationale=choice.reason,
        reasoning_trace={"path": "deterministic_table", "retry_count": retry_count},
        iterations_used=1,
    )


SYSTEM_PROMPT = """You are the recovery agent for failed payments. Classify the failure and pick ONE strategy.

Diagnosis classes: INSUFFICIENT_FUNDS, CUSTOMER_AUTH_REQUIRED, INSTRUMENT_INVALID, NETWORK_INFRA, BANK_DOWNTIME, DUPLICATE_SELF_HEALED, UNKNOWN.
Strategies: S1_IMMEDIATE_RETRY, S2_DELAYED_RETRY, S3_NOTIFY_WITH_LINK, S4_ALT_PAYMENT_FLOW, S5_HUMAN_ESCALATION, S6_STOP_RECOVERY.

Rules you must respect:
- Amount at/above the approval ceiling, unknown diagnosis, or confidence below the floor -> S5_HUMAN_ESCALATION.
- Failure older than 48h -> S6_STOP_RECOVERY.
- Payment already captured -> S6_STOP_RECOVERY.
- No saved token -> never propose retry; use S3.
- Never invent strategies or fields outside the schema.

Respond with ONLY a JSON object:
{"diagnosis": "...", "diagnosis_confidence": 0.0-1.0, "strategy_id": "...", "strategy_confidence": 0.0-1.0, "params": {}, "rationale": "one short sentence"}
"""


def _build_user_prompt(payment: Payment, customer: Customer | None, ctx: CaseContext, cfg: PolicyConfig) -> str:
    return json.dumps(
        {
            "amount_minor": payment.amount_minor,
            "currency": payment.currency,
            "method": payment.method,
            "error_code": payment.error_code,
            "error_reason": payment.error_reason,
            "error_source": payment.error_source,
            "error_description": payment.error_description,
            "failure_age_hours": round(ctx.age_hours, 1),
            "downtime_active": ctx.downtime_active,
            "notifications_sent_7d": ctx.notify_count,
            "customer": {
                "tenure_days": customer.tenure_days if customer else 0,
                "prior_failures_90d": customer.prior_failures_90d if customer else 0,
                "has_saved_token": ctx.has_token,
            },
            "policy": {
                "approval_limit_minor": cfg.approval_limit_minor,
                "confidence_floor": cfg.confidence_floor,
                "max_retries": cfg.max_retries,
            },
        },
        sort_keys=True,
    )


def _validate_llm_output(raw: dict) -> tuple[DiagnosisClass, str] | None:
    try:
        d = DiagnosisClass(raw["diagnosis"])
        s = raw["strategy_id"]
        if s not in st.ALL_STRATEGIES:
            return None
        for k in ("diagnosis_confidence", "strategy_confidence"):
            v = float(raw[k])
            if not (0.0 <= v <= 1.0):
                return None
        return d, s
    except (KeyError, ValueError, TypeError):
        return None


async def _call_llm(user_prompt: str) -> tuple[dict, dict] | None:
    s = get_settings()
    headers = {"Authorization": f"Bearer {s.llm_api_key}", "Content-Type": "application/json"}
    body = {
        "model": s.llm_model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    }
    async with httpx.AsyncClient(timeout=s.agent_llm_timeout_s) as client:
        resp = await client.post(f"{s.llm_base_url.rstrip('/')}/chat/completions", headers=headers, json=body)
    if resp.status_code != 200:
        return None
    data = resp.json()
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})
    return json.loads(content), usage


async def decide_and_persist(
    session: AsyncSession,
    case: RecoveryCase,
    payment: Payment,
    customer: Customer | None,
    ctx: CaseContext,
    cfg: PolicyConfig,
    *,
    retry_count: int,
) -> AgentDecision:
    """Produce + persist the decision for a case, then stamp the case row."""
    decision: AgentDecision | None = None
    if get_settings().llm_configured:
        for _attempt in range(MAX_LLM_ATTEMPTS):
            try:
                out = await _call_llm(_build_user_prompt(payment, customer, ctx, cfg))
                if out is None:
                    continue
                raw, usage = out
                valid = _validate_llm_output(raw)
                if valid is None:
                    continue
                d, s = valid
                decision = AgentDecision(
                    origin=DecisionOrigin.LLM,
                    model=get_settings().llm_model,
                    prompt_tokens=usage.get("prompt_tokens"),
                    completion_tokens=usage.get("completion_tokens"),
                    diagnosis_class=d,
                    diagnosis_confidence=float(raw["diagnosis_confidence"]),
                    strategy_id=s,
                    strategy_confidence=float(raw["strategy_confidence"]),
                    params=dict(raw.get("params") or {}),
                    rationale=str(raw.get("rationale", ""))[:500],
                    reasoning_trace={"path": "llm", "attempt": _attempt + 1},
                    iterations_used=1,
                )
                break
            except Exception:
                continue

    if decision is None:
        decision = _fallback_decision(payment, ctx, cfg, retry_count)

    decision.case_id = case.id
    decision.decision_ref = await case_service.next_ref(session, "decision_ref", "DEC")
    decision.latency_ms = 0
    session.add(decision)
    await session.flush()

    case.diagnosis_class = decision.diagnosis_class
    case.strategy_id = decision.strategy_id
    case.agent_confidence = decision.diagnosis_confidence
    await session.flush()

    await audit.append_event(
        session,
        case_id=case.id,
        actor=Actor.AGENT,
        event_type="DECISION_RECORDED",
        detail={
            "decision_ref": decision.decision_ref,
            "origin": decision.origin.value,
            "diagnosis": decision.diagnosis_class.value,
            "strategy": decision.strategy_id,
            "confidence": float(decision.diagnosis_confidence),
            "retry_count": retry_count,
        },
    )
    return decision
