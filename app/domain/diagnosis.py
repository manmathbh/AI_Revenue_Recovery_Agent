"""Deterministic error-code -> diagnosis mapping (REVENUE_RISK_ENGINE §4).

The LLM may refine this; this module is the deterministic prior AND the fallback.
"""

from __future__ import annotations

from app.db.enums import DiagnosisClass

# error_reason (structured) -> diagnosis class.
REASON_MAP: dict[str, DiagnosisClass] = {
    "insufficient_funds": DiagnosisClass.INSUFFICIENT_FUNDS,
    "gateway_error": DiagnosisClass.NETWORK_INFRA,
    "network_error": DiagnosisClass.NETWORK_INFRA,
    "timeout_error": DiagnosisClass.NETWORK_INFRA,
    "timeout": DiagnosisClass.NETWORK_INFRA,
    "authentication_failed": DiagnosisClass.CUSTOMER_AUTH_REQUIRED,
    "wrong_pin": DiagnosisClass.CUSTOMER_AUTH_REQUIRED,
    "pin_error": DiagnosisClass.CUSTOMER_AUTH_REQUIRED,
    "otp_timeout": DiagnosisClass.CUSTOMER_AUTH_REQUIRED,
    "card_expired": DiagnosisClass.INSTRUMENT_INVALID,
    "invalid_card": DiagnosisClass.INSTRUMENT_INVALID,
    "card_declined": DiagnosisClass.INSTRUMENT_INVALID,
    "bank_error": DiagnosisClass.BANK_DOWNTIME,
    "bank_down": DiagnosisClass.BANK_DOWNTIME,
    "downtime": DiagnosisClass.BANK_DOWNTIME,
    "insufficient_balance": DiagnosisClass.INSUFFICIENT_FUNDS,
    "unknown_failure": DiagnosisClass.UNKNOWN,
}

# error_code (less specific) -> diagnosis class (lower-confidence prior).
CODE_MAP: dict[str, DiagnosisClass] = {
    "GATEWAY_ERROR": DiagnosisClass.NETWORK_INFRA,
    "TIMEOUT_ERROR": DiagnosisClass.NETWORK_INFRA,
    "BAD_REQUEST_ERROR": DiagnosisClass.UNKNOWN,
    "SERVER_ERROR": DiagnosisClass.NETWORK_INFRA,
    "UNKNOWN_ERROR": DiagnosisClass.UNKNOWN,
}

# Base confidence anchored to evidence strength (REVENUE_RISK_ENGINE §4).
BASE_CONFIDENCE_REASON = 0.90
BASE_CONFIDENCE_CODE = 0.70
BASE_CONFIDENCE_UNKNOWN = 0.40


def diagnose(
    error_reason: str | None,
    error_code: str | None,
    error_source: str | None = None,
) -> tuple[DiagnosisClass, float]:
    """Return (diagnosis, base confidence) from structured error fields alone."""
    if error_reason and error_reason in REASON_MAP:
        d = REASON_MAP[error_reason]
        return d, BASE_CONFIDENCE_REASON
    if error_code and error_code in CODE_MAP:
        return CODE_MAP[error_code], BASE_CONFIDENCE_CODE
    return DiagnosisClass.UNKNOWN, BASE_CONFIDENCE_UNKNOWN
