"""Webhook ingestion: dedupe -> upsert payment/customer -> open exactly one case.

Idempotency guarantees (TESTING.md e2e #3):
- webhook_events.event_id UNIQUE -> replayed deliveries are skipped,
- recovery_cases.payment_id UNIQUE -> a payment ever yields at most one case.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Actor, DiagnosisClass, ExecutionMode, PaymentStatus, WebhookEventType
from app.db.models import Customer, Merchant, Payment, WebhookEvent
from app.domain import strategies as st
from app.services import audit, case_service
from app.verification import service as verification

DEMO_ACCOUNT_ID = "acc_demo"


@dataclass(frozen=True)
class IngestResult:
    event_id: str
    processed: bool
    duplicated: bool
    case_ref: str | None = None
    note: str = ""


def _mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    local, _, domain = email.partition("@")
    return f"{local[0]}***@{domain}" if local else None


def _mask_name(name: str | None) -> str:
    if not name:
        return "C***r"
    return f"{name[0]}***{name[-1]}" if len(name) > 2 else f"{name[0]}***"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _classify(event_name: str) -> WebhookEventType:
    try:
        return WebhookEventType(event_name)
    except ValueError:
        return WebhookEventType.OTHER


async def get_or_create_demo_merchant(session: AsyncSession) -> Merchant:
    row = await session.execute(select(Merchant).where(Merchant.name == "Recoup Demo Merchant"))
    m = row.scalar_one_or_none()
    if m is None:
        m = Merchant(name="Recoup Demo Merchant", rzp_key_id=DEMO_ACCOUNT_ID, policy_config={})
        session.add(m)
        await session.flush()
    return m


async def _upsert_customer(
    session: AsyncSession, merchant: Merchant, payload_ent: dict, gt_customer: dict | None
) -> Customer | None:
    contact = payload_ent.get("contact") or (gt_customer or {}).get("contact")
    email = payload_ent.get("email") or (gt_customer or {}).get("email")
    rzp_customer_id = payload_ent.get("customer_id") or (gt_customer or {}).get("rzp_customer_id")
    if not contact and not email:
        return None

    gt = gt_customer or {}
    if rzp_customer_id:
        row = await session.execute(select(Customer).where(Customer.rzp_customer_id == rzp_customer_id))
        existing = row.scalar_one_or_none()
        if existing is not None:
            return existing

    c = Customer(
        merchant_id=merchant.id,
        rzp_customer_id=rzp_customer_id,
        masked_name=gt.get("masked_name") or _mask_name(gt.get("name")),
        contact_hash=_sha(contact if contact else (email or "")),
        email_masked=gt.get("email_masked") or _mask_email(email),
        tenure_days=int(gt.get("tenure_days", 0)),
        lifetime_value_minor=int(gt.get("lifetime_value_minor", 0)),
        prior_failures_90d=int(gt.get("prior_failures_90d", 0)),
        prior_recoveries_90d=int(gt.get("prior_recoveries_90d", 0)),
        successful_payments=int(gt.get("successful_payments", 0)),
        has_saved_token=bool(gt.get("has_saved_token", False)),
        mandate_status=gt.get("mandate_status"),
    )
    session.add(c)
    await session.flush()
    return c


async def _upsert_payment(
    session: AsyncSession, merchant: Merchant, ent: dict, customer_id: uuid.UUID | None, is_simulated: bool
) -> Payment:
    rzp_id = ent["id"]
    row = await session.execute(select(Payment).where(Payment.rzp_payment_id == rzp_id))
    payment = row.scalar_one_or_none()
    fields = {
        "merchant_id": merchant.id,
        "customer_id": customer_id,
        "rzp_order_id": ent.get("order_id"),
        "status": PaymentStatus(ent.get("status", "created")),
        "amount_minor": int(ent.get("amount", 0)),
        "currency": ent.get("currency", "INR"),
        "method": ent.get("method"),
        "error_code": ent.get("error_code"),
        "error_source": ent.get("error_source"),
        "error_step": ent.get("error_step"),
        "error_reason": ent.get("error_reason"),
        "error_description": ent.get("error_description"),
        "bank": ent.get("bank"),
        "card_last4": (ent.get("card_id") or "")[-4:] or None,
        "is_simulated": is_simulated,
        "rzp_created_at": datetime.fromtimestamp(ent["created_at"], tz=UTC),
    }
    if payment is None:
        payment = Payment(rzp_payment_id=rzp_id, **fields)
        session.add(payment)
        await session.flush()
    else:
        for k, v in fields.items():
            setattr(payment, k, v)
        await session.flush()
    return payment


async def ingest_event(
    session: AsyncSession,
    event: dict,
    *,
    signature_valid: bool = True,
    ground_truth: dict | None = None,
    is_simulated: bool = False,
) -> IngestResult:
    """Ingest one Razorpay-shaped webhook event. Safe to replay."""
    event_id = event["id"]
    event_name = event.get("event", "other")

    dup = await session.execute(select(WebhookEvent).where(WebhookEvent.event_id == event_id))
    if dup.scalar_one_or_none() is not None:
        return IngestResult(event_id, processed=False, duplicated=True, note="duplicate delivery skipped")

    wh = WebhookEvent(
        provider="razorpay",
        event_id=event_id,
        event_type=event_name,
        signature_valid=signature_valid,
        payload=event,
    )
    session.add(wh)
    await session.flush()

    if not signature_valid:
        await audit.append_event(
            session, case_id=None, actor=Actor.SYSTEM, event_type="WEBHOOK_REJECTED",
            detail={"event_id": event_id, "reason": "invalid signature"},
        )
        return IngestResult(event_id, processed=False, duplicated=False, note="invalid signature")

    etype = _classify(event_name)
    if etype not in (WebhookEventType.PAYMENT_FAILED, WebhookEventType.PAYMENT_CAPTURED):
        return IngestResult(event_id, processed=True, duplicated=False, note=f"{event_name} recorded only")

    merchant = await get_or_create_demo_merchant(session)
    ent = event["payload"]["payment"]["entity"]
    gt = ground_truth or {}
    customer = await _upsert_customer(session, merchant, ent, gt.get("customer"))
    payment = await _upsert_payment(session, merchant, ent, customer.id if customer else None, is_simulated)

    if etype == WebhookEventType.PAYMENT_CAPTURED:
        existing_case = await case_service.get_case_by_payment(session, payment.id)
        if existing_case is None:
            return IngestResult(event_id, processed=True, duplicated=False, note="capture for unknown case recorded")
        # Self-heal: the capture IS the evidence. Stamp diagnosis, then recover.
        existing_case.diagnosis_class = DiagnosisClass.DUPLICATE_SELF_HEALED
        existing_case.strategy_id = st.S6
        await session.flush()
        await verification.record_capture(
            session, existing_case, payment, gateway_ref=ent.get("id"),
            mode=ExecutionMode.SIMULATED,
            source="webhook_self_heal",
        )
        return IngestResult(event_id, processed=True, duplicated=False, case_ref=existing_case.case_ref, note="self-healed")

    # payment.failed -> exactly one case per payment.
    existing = await case_service.get_case_by_payment(session, payment.id)
    if existing is not None:
        return IngestResult(event_id, processed=True, duplicated=False, case_ref=existing.case_ref, note="case already open")

    sla_base = datetime.fromtimestamp(ent["created_at"], tz=UTC)
    case = await case_service.create_case(
        session,
        merchant_id=merchant.id,
        payment_id=payment.id,
        customer_id=customer.id if customer else None,
        sla_deadline_at=sla_base,  # re-stamped by risk enrichment
        ground_truth={
            "scenario": gt.get("scenario"),
            "case_key": gt.get("case_key"),
            "recoverable": gt.get("recoverable"),
            "simulated_capture_probability": gt.get("simulated_capture_probability"),
            "expected_diagnosis": gt.get("expected_diagnosis"),
            "expected_strategy": gt.get("expected_strategy"),
            "customer": gt.get("customer"),
        },
    )
    case.retry_count = int(gt.get("prior_attempts", 0))
    await session.flush()
    return IngestResult(event_id, processed=True, duplicated=False, case_ref=case.case_ref, note="case created")
