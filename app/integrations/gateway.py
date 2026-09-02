"""GatewayPort seam: real Razorpay adapter vs labeled simulator (RAZORPAY_INTEGRATION §3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PaymentSnapshot:
    rzp_payment_id: str
    status: str  # created | authorized | captured | failed
    amount_minor: int
    method: str | None
    error_reason: str | None
    error_code: str | None
    error_source: str | None
    error_description: str | None


@dataclass(frozen=True)
class RetryChargeRequest:
    payment_id: str
    order_id: str | None
    customer_id: str | None
    amount_minor: int
    currency: str
    method: str | None
    token_available: bool
    capture_probability: float | None = None  # simulator-only knob


@dataclass(frozen=True)
class ChargeResult:
    success: bool
    status: str  # captured | failed
    gateway_ref: str | None = None
    error_reason: str | None = None
    simulated: bool = False


@dataclass(frozen=True)
class PaymentLinkResult:
    success: bool
    link_id: str | None = None
    short_url: str | None = None
    simulated: bool = False
    error: str | None = None


class GatewayPort(Protocol):
    async def retry_charge(self, req: RetryChargeRequest) -> ChargeResult: ...
    async def fetch_payment(self, rzp_payment_id: str) -> PaymentSnapshot: ...
    async def create_payment_link(
        self, *, amount_minor: int, currency: str, customer_name: str,
        contact: str | None, email: str | None, reference_id: str,
    ) -> PaymentLinkResult: ...
