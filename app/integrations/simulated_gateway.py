"""Simulated gateway adapter — labeled SIMULATED (RAZORPAY_INTEGRATION §3).

There is no public "retry this failed payment" API; server-side token charges are
activation-gated and unavailable in test mode. The simulator models outcomes with
a seeded RNG + per-case capture probability so batch results are reproducible.
Every result carries `simulated=True` and is surfaced as SIMULATED end-to-end.
"""

from __future__ import annotations

import random

from app.integrations.gateway import ChargeResult, PaymentLinkResult, RetryChargeRequest

# Default per-diagnosis retry success probabilities (when no ground truth).
DEFAULT_PROBABILITIES = {
    "INSUFFICIENT_FUNDS": 0.55,
    "NETWORK_INFRA": 0.80,
    "BANK_DOWNTIME": 0.75,
    "CUSTOMER_AUTH_REQUIRED": 0.45,
    "INSTRUMENT_INVALID": 0.0,
    "UNKNOWN": 0.0,
}


class SimulatedGatewayAdapter:
    def __init__(self, seed: int = 42):
        self._rng = random.Random(seed)
        self._rolls: dict[str, bool] = {}

    def _latent(self, key: str, probability: float) -> bool:
        """Single latent roll per case: the customer either will or won't pay."""
        if key not in self._rolls:
            self._rolls[key] = self._rng.random() < probability
        return self._rolls[key]

    async def retry_charge(self, req: RetryChargeRequest) -> ChargeResult:
        prob = getattr(req, "capture_probability", None) or 0.0
        will_pay = self._latent(req.payment_id, prob)
        if will_pay:
            return ChargeResult(
                success=True, status="captured",
                gateway_ref=f"sim_txn_{req.payment_id}", simulated=True,
            )
        return ChargeResult(
            success=False, status="failed",
            error_reason="charge_declined", simulated=True,
        )

    async def create_payment_link(self, *, amount_minor, currency, customer_name,
                                  contact, email, reference_id) -> PaymentLinkResult:
        return PaymentLinkResult(
            success=True,
            link_id=f"plink_sim_{reference_id}",
            short_url=f"https://sim.recoup/l/{reference_id}",
            simulated=True,
        )

    async def simulate_link_payment(self, payment_id: str, probability: float) -> ChargeResult:
        will_pay = self._latent(payment_id, probability)
        if will_pay:
            return ChargeResult(
                success=True, status="captured",
                gateway_ref=f"sim_plink_{payment_id}", simulated=True,
            )
        return ChargeResult(
            success=False, status="failed", error_reason="link_not_paid", simulated=True,
        )

    async def fetch_payment(self, rzp_payment_id: str):
        # Simulator does not maintain remote state; callers use the DB mirror.
        raise NotImplementedError
