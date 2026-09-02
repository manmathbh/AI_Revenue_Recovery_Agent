"""SQLAlchemy 2.0 ORM models — the 13-table audit-oriented schema.

Conventions (DATA_MODEL.md): UUID PKs, timestamptz UTC, money as BIGINT paise,
append-only audit tables, immutability where audit requires it.
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.db.enums import (
    ActionStatus,
    ActionType,
    Actor,
    CaseOutcome,
    CaseStatus,
    DecisionOrigin,
    DiagnosisClass,
    EscalationReasonCode,
    EscalationStatus,
    ExecutionMode,
    NotificationChannel,
    NotificationStatus,
    PaymentStatus,
    PolicyVerdict,
    RiskBand,
)


def uuid7() -> _uuid.UUID:
    """Time-ordered UUID v7 (millisecond timestamp + random tail)."""
    import time

    ms = int(time.time() * 1000)
    rand = _uuid.uuid4().bytes
    b = bytearray(16)
    b[0:6] = ms.to_bytes(6, "big")
    b[6] = (rand[6] & 0x0F) | 0x70  # version 7
    b[7] = rand[7]
    b[8] = (rand[8] & 0x3F) | 0x80  # variant 10
    b[9:16] = rand[9:16]
    return _uuid.UUID(bytes=bytes(b))


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Merchant(Base):
    __tablename__ = "merchants"

    id: Mapped[_uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    rzp_key_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    policy_config: Mapped[dict] = mapped_column(JSONB, nullable=False)

    customers: Mapped[list[Customer]] = relationship(back_populates="merchant")


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("merchant_id", "contact_hash", name="uq_customer_merchant_contact"),
    )

    id: Mapped[_uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    merchant_id: Mapped[_uuid.UUID] = mapped_column(
        UUID, ForeignKey("merchants.id"), nullable=False
    )
    rzp_customer_id: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    masked_name: Mapped[str] = mapped_column(Text, nullable=False)
    contact_hash: Mapped[str] = mapped_column(Text, nullable=False)
    email_masked: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenure_days: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    lifetime_value_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    prior_failures_90d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prior_recoveries_90d: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_payments: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_saved_token: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    mandate_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    merchant: Mapped[Merchant] = relationship(back_populates="customers")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[_uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    merchant_id: Mapped[_uuid.UUID] = mapped_column(
        UUID, ForeignKey("merchants.id"), nullable=False
    )
    customer_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("customers.id"), nullable=True
    )
    rzp_payment_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    rzp_order_id: Mapped[str | None] = mapped_column(Text, index=True, nullable=True)
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, native_enum=False), default=PaymentStatus.CREATED, nullable=False
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="INR", nullable=False)
    method: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    bank: Mapped[str | None] = mapped_column(Text, nullable=True)
    card_last4: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_simulated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    rzp_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"

    id: Mapped[_uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    case_ref: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    merchant_id: Mapped[_uuid.UUID] = mapped_column(
        UUID, ForeignKey("merchants.id"), nullable=False
    )
    payment_id: Mapped[_uuid.UUID] = mapped_column(
        UUID, ForeignKey("payments.id"), unique=True, nullable=False
    )
    customer_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("customers.id"), nullable=True
    )
    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, native_enum=False), default=CaseStatus.DETECTED, nullable=False
    )
    risk_score: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    risk_band: Mapped[RiskBand | None] = mapped_column(Enum(RiskBand, native_enum=False), nullable=True)
    diagnosis_class: Mapped[DiagnosisClass | None] = mapped_column(
        Enum(DiagnosisClass, native_enum=False), nullable=True
    )
    strategy_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_confidence: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    retry_count: Mapped[int] = mapped_column(SmallInteger, default=0, nullable=False)
    last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recovered_amount_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    outcome: Mapped[CaseOutcome | None] = mapped_column(Enum(CaseOutcome, native_enum=False), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_deadline_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ground_truth: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    payment: Mapped[Payment] = relationship()
    customer: Mapped[Customer | None] = relationship()

    __table_args__ = (
        Index("ix_cases_status_active", "status", postgresql_where=status.in_(tuple(s.value for s in [CaseStatus.DETECTED, CaseStatus.ANALYZING, CaseStatus.DIAGNOSED, CaseStatus.PLANNED, CaseStatus.POLICY_CHECK, CaseStatus.AWAITING_APPROVAL, CaseStatus.APPROVED, CaseStatus.EXECUTING, CaseStatus.VERIFYING]))),
        Index("ix_cases_band_sla", "risk_band", "sla_deadline_at"),
        Index("ix_cases_merchant_created", "merchant_id", "created_at"),
    )


class AgentDecision(Base):
    __tablename__ = "agent_decisions"

    id: Mapped[_uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    case_id: Mapped[_uuid.UUID] = mapped_column(
        UUID, ForeignKey("recovery_cases.id"), nullable=False
    )
    decision_ref: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    origin: Mapped[DecisionOrigin] = mapped_column(Enum(DecisionOrigin, native_enum=False), nullable=False)
    model: Mapped[str | None] = mapped_column(Text, nullable=True)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diagnosis_class: Mapped[DiagnosisClass] = mapped_column(Enum(DiagnosisClass, native_enum=False), nullable=False)
    diagnosis_confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    strategy_id: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_confidence: Mapped[float] = mapped_column(Numeric(3, 2), nullable=False)
    params: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    reasoning_trace: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    iterations_used: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"

    id: Mapped[_uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    case_id: Mapped[_uuid.UUID] = mapped_column(
        UUID, ForeignKey("recovery_cases.id"), nullable=False
    )
    decision_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("agent_decisions.id"), nullable=True
    )
    proposed_action: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[PolicyVerdict] = mapped_column(Enum(PolicyVerdict, native_enum=False), nullable=False)
    rule_results: Mapped[dict] = mapped_column(JSONB, nullable=False)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_policy_case_created", "case_id", "created_at"),)


class RecoveryAction(Base):
    __tablename__ = "recovery_actions"
    __table_args__ = (
        UniqueConstraint("case_id", "action_type", "attempt_no", name="uq_action_case_type_attempt"),
        UniqueConstraint("idempotency_key", name="uq_action_idempotency"),
    )

    id: Mapped[_uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    action_ref: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    case_id: Mapped[_uuid.UUID] = mapped_column(
        UUID, ForeignKey("recovery_cases.id"), nullable=False
    )
    action_type: Mapped[ActionType] = mapped_column(Enum(ActionType, native_enum=False), nullable=False)
    attempt_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    execution_mode: Mapped[ExecutionMode] = mapped_column(Enum(ExecutionMode, native_enum=False), nullable=False)
    gateway_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ActionStatus] = mapped_column(
        Enum(ActionStatus, native_enum=False), default=ActionStatus.PENDING, nullable=False
    )
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[_uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    case_id: Mapped[_uuid.UUID] = mapped_column(
        UUID, ForeignKey("recovery_cases.id"), nullable=False
    )
    action_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("recovery_actions.id"), nullable=True
    )
    channel: Mapped[NotificationChannel] = mapped_column(Enum(NotificationChannel, native_enum=False), nullable=False)
    rendered_subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    rendered_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[NotificationStatus] = mapped_column(
        Enum(NotificationStatus, native_enum=False), default=NotificationStatus.QUEUED, nullable=False
    )
    suppressed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Escalation(Base):
    __tablename__ = "escalations"

    id: Mapped[_uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    escalation_ref: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    case_id: Mapped[_uuid.UUID] = mapped_column(
        UUID, ForeignKey("recovery_cases.id"), nullable=False
    )
    reason_code: Mapped[EscalationReasonCode] = mapped_column(Enum(EscalationReasonCode, native_enum=False), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[EscalationStatus] = mapped_column(
        Enum(EscalationStatus, native_enum=False), default=EscalationStatus.OPEN, nullable=False
    )
    decided_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[_uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    provider: Mapped[str] = mapped_column(Text, default="razorpay", nullable=False)
    event_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[_uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    case_id: Mapped[_uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("recovery_cases.id"), nullable=True
    )
    actor: Mapped[Actor] = mapped_column(Enum(Actor, native_enum=False), nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    prev_event_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_audit_case", "case_id", "created_at"),)


class Counter(Base):
    """Utility counter for human-readable refs (RC/DEC/ACT/ESC sequences).

    A small extra table beyond DATA_MODEL's 13 — it only mints monotonic ids for
    audit-friendly references; no business data lives here.
    """

    __tablename__ = "counters"

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)


class EvalRun(Base):
    __tablename__ = "eval_runs"

    id: Mapped[_uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    run_ref: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    dataset_seed: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    config_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    report: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class EvalCaseResult(Base):
    __tablename__ = "eval_case_results"
    __table_args__ = (UniqueConstraint("run_id", "case_id", name="uq_eval_run_case"),)

    id: Mapped[_uuid.UUID] = mapped_column(UUID, primary_key=True, default=uuid7)
    run_id: Mapped[_uuid.UUID] = mapped_column(UUID, ForeignKey("eval_runs.id"), nullable=False)
    case_id: Mapped[_uuid.UUID] = mapped_column(
        UUID, ForeignKey("recovery_cases.id"), nullable=False
    )
    expected_diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_diagnosis: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_strategy: Mapped[str | None] = mapped_column(Text, nullable=True)
    actual_strategy: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[str | None] = mapped_column(Text, nullable=True)
    recovered_amount_minor: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
