"""Bounded strategy catalog + deterministic decision matrix (RECOVERY_STRATEGIES.md).

This module is BOTH the deterministic fallback table (AGENT_DESIGN §8) and the
prior the LLM is prompted with. The catalog is closed: the agent may only choose
from S1..S6, never invent strategies.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.db.enums import DiagnosisClass

S1 = "S1_IMMEDIATE_RETRY"
S2 = "S2_DELAYED_RETRY"
S3 = "S3_NOTIFY_WITH_LINK"
S4 = "S4_ALT_PAYMENT_FLOW"
S5 = "S5_HUMAN_ESCALATION"
S6 = "S6_STOP_RECOVERY"

ALL_STRATEGIES = (S1, S2, S3, S4, S5, S6)

# Human-readable catalog (surfaced in UI / prompts).
STRATEGY_CATALOG: dict[str, dict] = {
    S1: {"name": "Immediate retry", "action": "RETRY_CHARGE", "risk": "low"},
    S2: {"name": "Delayed retry", "action": "RETRY_CHARGE", "risk": "low"},
    S3: {"name": "Notify with link", "action": "SEND_RECOVERY_LINK", "risk": "low"},
    S4: {"name": "Alternate payment flow", "action": "SEND_RECOVERY_LINK", "risk": "low"},
    S5: {"name": "Human escalation", "action": "CREATE_ESCALATION", "risk": "none"},
    S6: {"name": "Stop recovery", "action": None, "risk": "none"},
}

# Delayed-retry default delay (salary-cycle timing; RECOVERY_STRATEGIES worked example).
DELAYED_RETRY_MINUTES = 240

# Cooldown schedule for retries: 30m -> 2h -> 8h (RECOVERY_STRATEGIES §3).
COOLDOWN_MINUTES = [30, 120, 480]


@dataclass(frozen=True)
class StrategyChoice:
    strategy_id: str
    confidence: float
    params: dict = field(default_factory=dict)
    reason: str = ""


def cooldown_minutes(attempt_no: int) -> int:
    """Spacing for the Nth retry (attempt_no >= 0), clamped [30m, 24h]."""
    idx = max(0, min(attempt_no, len(COOLDOWN_MINUTES) - 1))
    return COOLDOWN_MINUTES[idx]


def select_strategy(
    *,
    diagnosis: DiagnosisClass,
    retry_count: int,
    has_token: bool,
    amount_minor: int,
    confidence: float,
    age_hours: float,
    downtime_active: bool,
    approval_limit_minor: int,
    confidence_floor: float,
) -> StrategyChoice:
    """Deterministic strategy table (the fallback + the LLM's prior)."""

    if diagnosis == DiagnosisClass.DUPLICATE_SELF_HEALED:
        return StrategyChoice(S6, confidence, {}, "Payment already captured; stop.")

    # S11: stale (>48h) failures have decayed past recovery value.
    if age_hours > 48:
        return StrategyChoice(S6, confidence, {}, "Failure is stale (>48h); stop recovery.")

    # S06: high-value money requires human sign-off (P05).
    if amount_minor >= approval_limit_minor:
        return StrategyChoice(S5, confidence, {}, "Amount at/above approval ceiling; escalate.")

    # P06: low-confidence judgment must not touch money.
    if confidence < confidence_floor:
        return StrategyChoice(S5, confidence, {}, "Confidence below floor; escalate.")

    # S10: unknown diagnosis with any material risk -> human.
    if diagnosis == DiagnosisClass.UNKNOWN:
        return StrategyChoice(S5, confidence, {}, "Unknown diagnosis; escalate.")

    # S05: repeated failure (>=2 prior recovery attempts) -> human review.
    if retry_count >= 2:
        return StrategyChoice(S5, confidence, {}, "Repeated failures; escalate for review.")

    if diagnosis == DiagnosisClass.BANK_DOWNTIME:
        if downtime_active:
            return StrategyChoice(
                S2, confidence, {"delay_minutes": 60}, "Bank downtime active; wait then retry."
            )
        return StrategyChoice(S1, confidence, {}, "Downtime resolved; immediate retry.")

    if diagnosis == DiagnosisClass.INSUFFICIENT_FUNDS:
        if has_token:
            return StrategyChoice(
                S2, confidence, {"delay_minutes": DELAYED_RETRY_MINUTES},
                "Salary-cycle timing favors a delayed retry.",
            )
        return StrategyChoice(S3, confidence, {}, "No saved token; notify with link.")

    if diagnosis == DiagnosisClass.NETWORK_INFRA:
        if has_token:
            return StrategyChoice(S1, confidence, {}, "Transient fault; immediate retry.")
        return StrategyChoice(S3, confidence, {}, "No saved token; notify with link.")

    if diagnosis == DiagnosisClass.CUSTOMER_AUTH_REQUIRED:
        return StrategyChoice(S3, confidence, {}, "Customer action required; notify with link.")

    if diagnosis == DiagnosisClass.INSTRUMENT_INVALID:
        return StrategyChoice(
            S3, confidence, {"notify_purpose": "update_method"},
            "Invalid instrument; ask customer to update payment method.",
        )

    return StrategyChoice(S5, confidence, {}, "No safe automated path; escalate.")  # type: ignore[unreachable]
