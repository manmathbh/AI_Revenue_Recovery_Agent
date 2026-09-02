"""Policy engine rule verdicts (GUARDRAILS.md) — pure, deterministic."""

from datetime import UTC, datetime, timedelta

from app.db.enums import ActionType, CaseStatus, DiagnosisClass, PaymentStatus
from app.policy.config import DEFAULT_POLICY_CONFIG, PolicyConfig
from app.policy.engine import evaluate
from app.policy.rules import PolicyContext

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def ctx(**kw) -> PolicyContext:
    base = {
        "case_status": CaseStatus.POLICY_CHECK,
        "payment_status": PaymentStatus.FAILED,
        "captured_for_order": False,
        "amount_minor": 1_000_00,
        "retry_count": 0,
        "last_attempt_at": None,
        "diagnosis_class": DiagnosisClass.NETWORK_INFRA,
        "diagnosis_confidence": 0.9,
        "strategy_confidence": 0.9,
        "contact_count_7d": 0,
        "downtime_active": False,
        "age_hours": 1.0,
        "simulation_budget_remaining": 200,
        "proposed_action": ActionType.RETRY_CHARGE,
        "proposed_delay_minutes": None,
        "link_amount_minor": None,
        "channel": None,
        "existing_action": False,
        "config": PolicyConfig(),
        "now": NOW,
    }
    base.update(kw)
    return PolicyContext(**base)


def test_allow_happy():
    r = evaluate(ctx())
    assert r.verdict.value == "ALLOW"


def test_p03_max_retries():
    r = evaluate(ctx(retry_count=3))
    assert r.verdict.value == "BLOCK"
    assert r.triggered_rule_id == "P03"


def test_p05_amount_ceiling_escalates():
    r = evaluate(ctx(amount_minor=30_000_00, diagnosis_class=DiagnosisClass.INSUFFICIENT_FUNDS))
    assert r.verdict.value == "ESCALATE"
    assert r.triggered_rule_id == "P05"


def test_p06_low_confidence_escalates():
    r = evaluate(ctx(diagnosis_confidence=0.4, strategy_confidence=0.4))
    assert r.verdict.value == "ESCALATE"
    assert r.triggered_rule_id == "P06"


def test_p04_cooldown_waits():
    r = evaluate(ctx(retry_count=1, last_attempt_at=NOW - timedelta(minutes=10)))
    assert r.verdict.value == "WAIT"
    assert r.triggered_rule_id == "P04"


def test_p08_contact_cap():
    r = evaluate(ctx(proposed_action=ActionType.SEND_RECOVERY_LINK, contact_count_7d=3))
    assert r.verdict.value == "BLOCK"
    assert r.triggered_rule_id == "P08"


def test_p02_already_recovered():
    # P01 already rejects a non-failed payment; P02 handles captured-for-order
    # while the payment row still reads failed (short-circuit ordering).
    r = evaluate(ctx(payment_status=PaymentStatus.CAPTURED))
    assert r.verdict.value == "BLOCK"
    assert r.triggered_rule_id == "P01"

    r2 = evaluate(ctx(captured_for_order=True))
    assert r2.verdict.value == "BLOCK"
    assert r2.triggered_rule_id == "P02"


def test_p10_retry_forbidden_for_instrument_invalid():
    r = evaluate(ctx(diagnosis_class=DiagnosisClass.INSTRUMENT_INVALID))
    assert r.verdict.value == "BLOCK"
    assert r.triggered_rule_id == "P10"


def test_escalation_action_always_allowed():
    r = evaluate(ctx(proposed_action=ActionType.CREATE_ESCALATION, amount_minor=99_000_00, retry_count=5))
    assert r.verdict.value == "ALLOW"


def test_default_config_values():
    assert DEFAULT_POLICY_CONFIG["max_retries"] == 3
    assert DEFAULT_POLICY_CONFIG["approval_limit_minor"] == 25_000_00
    assert DEFAULT_POLICY_CONFIG["confidence_floor"] == 0.60
