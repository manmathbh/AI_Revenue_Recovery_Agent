"""Closed enums shared across the domain, API, and DB.

Stored as VARCHAR + CHECK (native_enum=False) so new values can be added via a
migration without PG ALTER TYPE dance; state legality is enforced in code anyway.
"""

from __future__ import annotations

import enum


class CaseStatus(str, enum.Enum):
    DETECTED = "DETECTED"
    ANALYZING = "ANALYZING"
    DIAGNOSED = "DIAGNOSED"
    PLANNED = "PLANNED"
    POLICY_CHECK = "POLICY_CHECK"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RECOVERED = "RECOVERED"
    CLOSED_UNRECOVERED = "CLOSED_UNRECOVERED"
    BLOCKED = "BLOCKED"
    ESCALATED = "ESCALATED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


TERMINAL_CASE_STATUSES = frozenset(
    {
        CaseStatus.RECOVERED,
        CaseStatus.CLOSED_UNRECOVERED,
        CaseStatus.EXPIRED,
        CaseStatus.CANCELLED,
        CaseStatus.BLOCKED,
        CaseStatus.ESCALATED,
        CaseStatus.FAILED,
    }
)

# Statuses a worker may claim (the active "in-flight" set).
ACTIVE_CASE_STATUSES = frozenset(
    {
        CaseStatus.DETECTED,
        CaseStatus.ANALYZING,
        CaseStatus.DIAGNOSED,
        CaseStatus.PLANNED,
        CaseStatus.POLICY_CHECK,
        CaseStatus.AWAITING_APPROVAL,
        CaseStatus.APPROVED,
        CaseStatus.EXECUTING,
        CaseStatus.VERIFYING,
    }
)


class RiskBand(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class DiagnosisClass(str, enum.Enum):
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"
    CUSTOMER_AUTH_REQUIRED = "CUSTOMER_AUTH_REQUIRED"
    INSTRUMENT_INVALID = "INSTRUMENT_INVALID"
    NETWORK_INFRA = "NETWORK_INFRA"
    BANK_DOWNTIME = "BANK_DOWNTIME"
    DUPLICATE_SELF_HEALED = "DUPLICATE_SELF_HEALED"
    UNKNOWN = "UNKNOWN"


class PaymentStatus(str, enum.Enum):
    CREATED = "created"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"


class PaymentMethod(str, enum.Enum):
    CARD = "card"
    UPI = "upi"
    NETBANKING = "netbanking"
    WALLET = "wallet"


class ActionType(str, enum.Enum):
    RETRY_CHARGE = "RETRY_CHARGE"
    SEND_RECOVERY_LINK = "SEND_RECOVERY_LINK"
    NOTIFY_CUSTOMER = "NOTIFY_CUSTOMER"
    CREATE_ESCALATION = "CREATE_ESCALATION"


class ExecutionMode(str, enum.Enum):
    REAL_RZP = "REAL_RZP"
    SIMULATED = "SIMULATED"
    OUTBOX = "OUTBOX"


class ActionStatus(str, enum.Enum):
    PENDING = "PENDING"
    GATED = "GATED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class DecisionOrigin(str, enum.Enum):
    LLM = "LLM"
    FALLBACK = "FALLBACK"


class PolicyVerdict(str, enum.Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"
    ESCALATE = "ESCALATE"
    WAIT = "WAIT"


class NotificationChannel(str, enum.Enum):
    SMS = "SMS"
    EMAIL = "EMAIL"


class NotificationStatus(str, enum.Enum):
    QUEUED = "QUEUED"
    SIMULATED_SENT = "SIMULATED_SENT"
    SUPPRESSED = "SUPPRESSED"


class EscalationReasonCode(str, enum.Enum):
    MAX_RETRIES_EXHAUSTED = "MAX_RETRIES_EXHAUSTED"
    AMOUNT_CEILING = "AMOUNT_CEILING"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    UNKNOWN_DIAGNOSIS = "UNKNOWN_DIAGNOSIS"
    EXECUTOR_ERROR = "EXECUTOR_ERROR"
    POLICY_DOUBLE_BLOCK = "POLICY_DOUBLE_BLOCK"


class EscalationStatus(str, enum.Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class CaseOutcome(str, enum.Enum):
    RECOVERED = "RECOVERED"
    SELF_HEALED = "SELF_HEALED"
    UNRECOVERED = "UNRECOVERED"


class Actor(str, enum.Enum):
    SYSTEM = "SYSTEM"
    AGENT = "AGENT"
    POLICY = "POLICY"
    EXECUTOR = "EXECUTOR"
    VERIFIER = "VERIFIER"
    HUMAN = "HUMAN"


class WebhookEventType(str, enum.Enum):
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_CAPTURED = "payment.captured"
    DOWNTIME_STARTED = "payment.downtime.started"
    DOWNTIME_RESOLVED = "payment.downtime.resolved"
    OTHER = "other"
