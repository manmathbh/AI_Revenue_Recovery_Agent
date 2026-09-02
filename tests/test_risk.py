"""Risk engine scoring + banding (pure)."""

from app.db.enums import DiagnosisClass, RiskBand
from app.risk import engine as risk


def test_score_bounded():
    score, band, comps = risk.compute_risk(
        amount_minor=1_000_00,
        diagnosis=DiagnosisClass.NETWORK_INFRA,
        lifetime_value_minor=1_000_000,
        tenure_days=365,
        prior_recoveries_90d=1,
        retry_count=0,
        age_hours=1,
    )
    assert 0 <= score <= 100
    assert band in RiskBand


def test_band_ordering():
    assert risk.band_for_score(80) == RiskBand.CRITICAL
    assert risk.band_for_score(60) == RiskBand.HIGH
    assert risk.band_for_score(40) == RiskBand.MEDIUM
    assert risk.band_for_score(10) == RiskBand.LOW


def test_higher_amount_scores_higher():
    low, _, _ = risk.compute_risk(
        amount_minor=1_000_00, diagnosis=DiagnosisClass.INSUFFICIENT_FUNDS,
        lifetime_value_minor=0, tenure_days=0, prior_recoveries_90d=0, retry_count=0, age_hours=1,
    )
    high, _, _ = risk.compute_risk(
        amount_minor=20_000_00, diagnosis=DiagnosisClass.INSUFFICIENT_FUNDS,
        lifetime_value_minor=0, tenure_days=0, prior_recoveries_90d=0, retry_count=0, age_hours=1,
    )
    assert high > low
