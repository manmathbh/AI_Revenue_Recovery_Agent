"""Deterministic revenue-risk scoring + banding (REVENUE_RISK_ENGINE.md).

Pure functions, integer paise amounts, UTC times. The score decides priority/SLA;
it does NOT choose strategies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.db.enums import DiagnosisClass, RiskBand

REVERSIBILITY_POINTS: dict[DiagnosisClass, float] = {
    DiagnosisClass.NETWORK_INFRA: 25.0,
    DiagnosisClass.BANK_DOWNTIME: 22.0,
    DiagnosisClass.INSUFFICIENT_FUNDS: 20.0,
    DiagnosisClass.CUSTOMER_AUTH_REQUIRED: 16.0,
    DiagnosisClass.DUPLICATE_SELF_HEALED: 25.0,
    DiagnosisClass.INSTRUMENT_INVALID: 6.0,
    DiagnosisClass.UNKNOWN: 10.0,
}

# Retry-history points by consumed attempt count.
RETRY_HISTORY_POINTS = {0: 15.0, 1: 12.0, 2: 8.0}


@dataclass(frozen=True)
class RiskComponents:
    amount: float
    reversibility: float
    customer_value: float
    retry_history: float
    time_sensitivity: float


def amount_component(amount_minor: int) -> float:
    return 30.0 * min(
        1.0, math.log(1 + amount_minor / 100_000) / math.log(1 + 25_000_000 / 100_000)
    )


def reversibility_component(diagnosis: DiagnosisClass) -> float:
    return REVERSIBILITY_POINTS.get(diagnosis, 10.0)


def customer_value_component(
    lifetime_value_minor: int, tenure_days: int, prior_recoveries_90d: int
) -> float:
    ltv = 10.0 * min(1.0, lifetime_value_minor / 500_000_00)
    tenure = 6.0 * min(1.0, tenure_days / 365)
    recovered = 4.0 if prior_recoveries_90d > 0 else 0.0
    return ltv + tenure + recovered


def retry_history_component(retry_count: int) -> float:
    return RETRY_HISTORY_POINTS.get(retry_count, 0.0) if retry_count <= 2 else 0.0


def time_sensitivity_component(age_hours: float) -> float:
    return 10.0 * max(0.0, 1.0 - age_hours / 48)


def compute_risk(
    *,
    amount_minor: int,
    diagnosis: DiagnosisClass,
    lifetime_value_minor: int,
    tenure_days: int,
    prior_recoveries_90d: int,
    retry_count: int,
    age_hours: float,
) -> tuple[int, RiskBand, RiskComponents]:
    comps = RiskComponents(
        amount=amount_component(amount_minor),
        reversibility=reversibility_component(diagnosis),
        customer_value=customer_value_component(
            lifetime_value_minor, tenure_days, prior_recoveries_90d
        ),
        retry_history=retry_history_component(retry_count),
        time_sensitivity=time_sensitivity_component(age_hours),
    )
    raw = sum(vars(comps).values())
    score = max(0, min(100, int(round(raw))))
    band = band_for_score(score)
    return score, band, comps


def band_for_score(score: int) -> RiskBand:
    if score >= 75:
        return RiskBand.CRITICAL
    if score >= 55:
        return RiskBand.HIGH
    if score >= 35:
        return RiskBand.MEDIUM
    return RiskBand.LOW
