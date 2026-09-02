"""Deterministic diagnosis + strategy matrix (fallback table). Pure."""

from app.db.enums import DiagnosisClass
from app.domain import strategies as st
from app.domain.diagnosis import diagnose


def test_diagnose_reason():
    d, conf = diagnose("insufficient_funds", "BAD_REQUEST_ERROR")
    assert d == DiagnosisClass.INSUFFICIENT_FUNDS
    assert conf >= 0.90


def test_diagnose_code_fallback():
    d, conf = diagnose(None, "GATEWAY_ERROR")
    assert d == DiagnosisClass.NETWORK_INFRA
    assert conf >= 0.70


def test_diagnose_unknown():
    d, conf = diagnose(None, None)
    assert d == DiagnosisClass.UNKNOWN
    assert conf == 0.40


BASE = {
    "amount_minor": 1_000_00,
    "confidence": 0.9,
    "age_hours": 10.0,
    "downtime_active": False,
    "approval_limit_minor": 25_000_00,
    "confidence_floor": 0.60,
}


def pick(diagnosis, retry_count=0, has_token=True, **kw):
    args = {**BASE, "diagnosis": diagnosis, "retry_count": retry_count, "has_token": has_token}
    args.update(kw)
    return st.select_strategy(**args).strategy_id


def test_insufficient_funds_token_retry():
    assert pick(DiagnosisClass.INSUFFICIENT_FUNDS, has_token=True) == st.S2


def test_insufficient_funds_no_token_notify():
    assert pick(DiagnosisClass.INSUFFICIENT_FUNDS, has_token=False) == st.S3


def test_network_infra_immediate():
    assert pick(DiagnosisClass.NETWORK_INFRA, has_token=True) == st.S1


def test_amount_ceiling_escalates():
    assert pick(DiagnosisClass.NETWORK_INFRA, amount_minor=30_000_00) == st.S5


def test_unknown_escalates():
    assert pick(DiagnosisClass.UNKNOWN) == st.S5


def test_repeated_failures_escalate():
    assert pick(DiagnosisClass.INSUFFICIENT_FUNDS, retry_count=2) == st.S5


def test_stale_stops():
    assert pick(DiagnosisClass.INSUFFICIENT_FUNDS, age_hours=60) == st.S6


def test_self_healed_stops():
    assert pick(DiagnosisClass.DUPLICATE_SELF_HEALED) == st.S6
