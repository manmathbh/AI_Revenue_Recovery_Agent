# RAZORPAY_INTEGRATION.md — Real vs simulated, verified against official docs

Sources checked: Razorpay API reference (Payments, Orders, Payment Links), Webhooks payloads & setup docs, Test Card Details page. Claims below are limited to documented behavior.

## 1. Capability matrix

| Capability | Razorpay support | Our mode |
|---|---|---|
| Receive `payment.failed` with structured error fields (`error_code`, `error_source`, `error_step`, `error_reason`) | ✅ Documented payload | **REAL** (test mode) |
| Receive `payment.captured` | ✅ Documented | **REAL** |
| Receive `payment.downtime.started/resolved/updated` | ✅ Documented | **REAL** (P1 feature) |
| Webhook signature: HMAC-SHA256 of **raw body** with webhook secret, hex, in `X-Razorpay-Signature` | ✅ Documented ("do not parse or cast the body") | **REAL** |
| Webhook test ping / resend from dashboard | ✅ | **REAL** (used in demos) |
| Fetch payment by id / list order payments | ✅ `GET /v1/payments/{id}`, `GET /v1/orders/{id}/payments` | **REAL** — used for pre-action re-check + reconciliation |
| Create Standard Payment Link (`POST /v1/payment_links`) with amount, customer{name,email,contact}, reference_id, notes, callback/redirect | ✅ Works on test keys | **REAL** — flagship recovery action |
| Payment Link notifications (SMS/email) actually delivered in test mode | ❌ Not sent in test mode | Outbox records rendered message; marked SIMULATED_SENT; link URL itself is real and payable |
| Resend notification for a link (`POST .../payment_links/{id}/notify_by`) | ✅ Documented | Called when outbox "sends" (harmless no-op delivery-wise in test) |
| Server-side charge of saved token / mandate debit | Exists as a product flow but activation-gated and constrained in test mode (card tokens valid ~3 days for subsequent debits) | **SIMULATED** behind `GatewayPort` — honest boundary |
| Single-call "retry this failed payment" API | ❌ Does not exist publicly | Not built; see PROBLEM_ANALYSIS A1 |

## 2. Auth & client

- HTTP Basic `key_id:key_secret` over HTTPS; test keys `rzp_test_...` from env only.
- Thin async wrapper on httpx (no heavy SDK dependency): `create_payment_link`, `fetch_payment`, `fetch_order_payments`, timeouts 10s, 2 retries with jitter on 5xx/timeouts, circuit breaker opens after 5 consecutive failures → executor parks actions.

## 3. The GatewayPort seam

```python
class GatewayPort(Protocol):
    async def retry_charge(self, req: RetryChargeRequest) -> ChargeResult: ...
    async def fetch_payment(self, rzp_payment_id: str) -> PaymentSnapshot: ...

class RazorpayAdapter(GatewayPort):        # real REST calls where supported
class SimulatedGatewayAdapter(GatewayPort): # seeded outcome model, labeled SIMULATED
```

`retry_charge` is only permitted by policy when `customer.has_saved_token or mandate_status=ACTIVE`; in buildathon runs it routes to the simulator, which:

1. Accepts a seeded RNG + the failure class,
2. Emits outcomes with realistic probabilities per class (e.g., INSUFFICIENT_FUNDS delayed-retry success ≈ 0.55; INSTRUMENT_INVALID retry success = 0),
3. Returns Razorpay-shaped results (`{status: captured|failed, error_reason, id}`),
4. Every result row carries `execution_mode=SIMULATED` end-to-end into UI and metrics.

**Why simulate at all?** Because claiming a fake "retry succeeded" against real APIs would be dishonest, and real token charges aren't available to us. The simulator makes recovery *measurement* possible while the REAL integration path (webhook → case → payment link → verified capture) demonstrates genuine Razorpay behavior.

## 4. Failure simulation for demos/tests

Two layers:
- **Real**: dashboard webhook "send test" + test cards (documented error-scenario cards exist, e.g., BAD_REQUEST_ERROR/GATEWAY_ERROR cards; mock bank Success/Failure buttons) drive genuine `payment.failed` events through our ingestion.
- **Synthetic**: dataset generator emits webhook-equivalent payloads (same schema incl. error fields) directly into the same ingestion endpoint/function — one code path, two sources.

## 5. Webhook handling contract

1. Raw body read (never parsed before verification).
2. `X-Razorpay-Signature` == HMAC-SHA256(raw, `RAZORPAY_WEBHOOK_SECRET`) else 401.
3. Dedupe on event id (unique index) — at-least-once delivery tolerated.
4. Order-insensitivity handled: `payment.captured` may arrive after we opened a case (late authorization/user retry is documented behavior) → Verification closes case as SELF_HEALED.
5. Replay tool: `scripts/replay_webhook.py` re-sends stored payloads (signature regenerated) for failure drills.

## 6. Test-mode limitations register (explicit)

| Limitation | Mitigation |
|---|---|
| No real money moves | Metrics are still exact arithmetic on real entity amounts |
| No SMS/email delivery | Outbox pattern; UI shows rendered message + SIMULATED badge |
| Card tokens expire ~3 days (test) | Retry sequencing keeps delays ≤72h TTL anyway |
| Some products (Route, Instant Settlements) irrelevant | Not used |
| Webhook endpoint must be public | Local dev uses ngrok/cloudflared tunnel OR synthetic injection path; both documented in README |
