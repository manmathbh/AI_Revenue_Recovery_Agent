"""Razorpay REST adapter — REAL test-mode calls (RAZORPAY_INTEGRATION §2).

Thin async httpx wrapper (no heavy SDK): fetch_payment, create_payment_link, with
timeouts, jittered retries, and a circuit breaker. `retry_charge` is NOT supported
by a public API and is left to the simulator (see simulated_gateway.py).
"""

from __future__ import annotations

import asyncio
import base64
import random
import time

import httpx

from app.config import get_settings
from app.integrations.gateway import PaymentLinkResult, PaymentSnapshot


class CircuitBreaker:
    """Opens after N consecutive failures; half-opens to probe recovery."""

    def __init__(self, threshold: int = 5, cooldown_s: float = 60.0):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at > self.cooldown_s:
            self._opened_at = None
            self._failures = 0
            return False
        return True

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            self._opened_at = time.monotonic()

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None


class RazorpayAdapter:
    def __init__(self, settings=None):
        s = settings or get_settings()
        self._base = s.razorpay_base_url.rstrip("/")
        self._key_id = s.razorpay_key_id
        self._secret = s.razorpay_key_secret
        self._timeout = s.rzp_timeout_s
        self._max_retries = s.rzp_max_retries
        self.breaker = CircuitBreaker(s.rzp_circuit_failure_threshold)

    def _auth_header(self) -> str:
        token = base64.b64encode(f"{self._key_id}:{self._secret}".encode()).decode()
        return f"Basic {token}"

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = f"{self._base}/{path.lstrip('/')}"
        headers = {"Authorization": self._auth_header()}
        headers.update(kwargs.pop("headers", {}))
        last_exc: Exception | None = None
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for attempt in range(self._max_retries + 1):
                if self.breaker.is_open:
                    raise RuntimeError("Razorpay circuit breaker open")
                try:
                    resp = await client.request(method, url, headers=headers, **kwargs)
                    if resp.status_code >= 500:
                        self.breaker.record_failure()
                        last_exc = RuntimeError(f"Razorpay 5xx: {resp.status_code}")
                    else:
                        self.breaker.record_success()
                        return resp
                except httpx.TimeoutException as e:
                    self.breaker.record_failure()
                    last_exc = e
                except httpx.HTTPError as e:
                    self.breaker.record_failure()
                    last_exc = e
                await asyncio.sleep((2 ** attempt) + random.uniform(0, 0.5))
        raise last_exc or RuntimeError("Razorpay request failed")

    async def fetch_payment(self, rzp_payment_id: str) -> PaymentSnapshot:
        resp = await self._request("GET", f"payments/{rzp_payment_id}")
        resp.raise_for_status()
        p = resp.json()
        return PaymentSnapshot(
            rzp_payment_id=p.get("id", rzp_payment_id),
            status=p.get("status", "failed"),
            amount_minor=int(p.get("amount", 0)),
            method=p.get("method"),
            error_reason=p.get("error_reason"),
            error_code=p.get("error_code"),
            error_source=p.get("error_source"),
            error_description=p.get("error_description"),
        )

    async def create_payment_link(
        self, *, amount_minor: int, currency: str, customer_name: str,
        contact: str | None, email: str | None, reference_id: str,
    ) -> PaymentLinkResult:
        body = {
            "amount": amount_minor,
            "currency": currency,
            "reference_id": reference_id,
            "description": "Recoup recovery payment",
            "customer": {
                "name": customer_name,
                "contact": contact or "+919999999999",
                "email": email or "customer@example.com",
            },
            "notify": {"sms": True, "email": True},
        }
        resp = await self._request("POST", "payment_links", json=body)
        data = resp.json()
        if resp.status_code not in (200, 201):
            return PaymentLinkResult(success=False, simulated=False, error=data.get("error", {}).get("description"))
        return PaymentLinkResult(
            success=True,
            link_id=data.get("id"),
            short_url=data.get("short_url"),
            simulated=False,
        )

    async def retry_charge(self, req) -> None:
        raise NotImplementedError("No public retry API; use SimulatedGatewayAdapter")
