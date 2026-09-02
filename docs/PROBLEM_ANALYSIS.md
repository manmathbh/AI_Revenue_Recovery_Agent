# PROBLEM_ANALYSIS.md — Track 03: AI Revenue Recovery

## 1. What Razorpay is actually asking for

Strip away the marketing language and the challenge asks for one thing:

> **A system that finds money a merchant has already earned but not yet received, figures out why it is stuck, takes the smallest safe action that is likely to un-stick it, proves whether that worked, and never does anything unsafe on its own.**

The evaluation bar listed in the problem statement tells us exactly what the judges will inspect:

| Evaluation bar | What it means in engineering terms |
|---|---|
| Measured money recovered across a batch | A reproducible batch run with real arithmetic, not vibes |
| Compliant escalation | Deterministic rules decide when a human must take over |
| Stopping rules | Bounded retries, cooldowns, TTLs — no infinite loops |
| Audit trail | Every decision reconstructable after the fact |
| Explainable decisions | A human-readable "why" per case, not raw chain-of-thought |
| Bounded & gated money actions | LLM proposes; deterministic policy disposes |
| Graceful failure handling | Every dependency can fail; the system degrades safely |

This is fundamentally a **reliability + workflow** problem with an **LLM as a reasoning component**, not an AI demo problem.

## 2. The merchant problem

For an Indian online merchant (D2C brand, SaaS, edtech, subscription business):

- **1–3% of card transactions fail** at authorization; UPI failure rates spike during bank downtimes and peak sale hours. At scale this is a material revenue leak.
- Failures are heterogeneous: insufficient funds, wrong PIN / authentication timeout, expired cards, issuer declines, network/gateway errors, bank downtime.
- Each cause needs a **different response**: retrying immediately after "insufficient funds" wastes attempts; retrying during a network blip works; an expired card can only be fixed by the customer.
- Merchants today either do nothing (lose the revenue), or blast generic "your payment failed" emails with no diagnosis, no prioritization, and no stopping rules.
- Subscription businesses additionally suffer involuntary churn: a failed auto-debit silently cancels otherwise happy customers.

## 3. What "revenue recovery" means in practice

Revenue recovery = converting an at-risk rupee into a captured rupee through a bounded intervention:

```
at_risk_revenue   = Σ amount of payments identified as recoverable
recovered_revenue = Σ amount of payments that reached `captured` AFTER our intervention
net_effect        = recovered_revenue − cost_of_interventions (notifications, retries, support time)
```

Recovery is only "real" when verified against the payment source of truth (Razorpay payment status / `payment.captured` webhook) — never claimed by the agent itself.

## 4. Revenue-loss scenarios in scope of the track

| Scenario | Signal | Recovery lever |
|---|---|---|
| Failed one-time payment | `payment.failed` webhook | Retry (token/mandate), notify customer w/ link |
| Checkout abandonment | Order created, no payment | Reminder + payment link |
| Failed subscription charge | `subscription.charged` failure | Mandate retry sequencing, dunning |
| Overdue B2B receivables | Invoice past due | Reminder ladder, promise-to-pay |
| Bank/network downtime | `payment.downtime.started` | Suppress retries, wait for resolution |

## 5. Realistic for a buildathon prototype

- ✅ **Failed payment recovery** — webhook-driven, structured error data available (`error_code`, `error_source`, `error_step`, `error_reason`), test-mode friendly, perfectly matches the Detect→Diagnose→Act→Verify loop.
- ✅ **Payment-link-based customer-directed recovery** — Payment Links API is fully supported on test keys (create/fetch/resend/cancel), and `payment.captured` closes the verification loop with a REAL Razorpay artifact.
- ✅ **Subscription-style mandate retry sequencing** — implementable as a policy pattern over the same engine (retry caps, cooldowns, expiry).
- ✅ **Downtime-aware suppression** — `payment.downtime.started/resolved` webhooks are documented; using them to block ill-timed retries is cheap and impressive.

## 6. NOT worth implementing (complexity traps)

- ❌ **B2B receivables / promise-to-pay** — no invoice entity in Razorpay core APIs to anchor on; would require inventing a whole second domain (invoices, credit terms). Different product.
- ❌ **Checkout abandonment funnel analytics** — requires frontend instrumentation and session data we don't have; overlaps with Razorpay Magic Checkout (their own product).
- ❌ **Hinglish voice recovery agent** — speech stack (STT/TTS/telephony) is a project by itself; impossible to evaluate reliability in judging time.
- ❌ **Trained ML risk model** — no training data at buildathon scale; a hand-tuned deterministic score is more explainable and more defensible.

## 7. What separates us from a basic AI wrapper

80% of submissions will be: webhook → GPT prompt → "here's what you should do" → chat UI. Weaknesses: no execution, no verification, no measurement, no safety.

Our separation:

1. **Closed loop**: detection → action → *verified* outcome → measured rupees. The agent's claim is checked against Razorpay state.
2. **Policy gate between brain and hands**: every side-effectful tool call passes a deterministic rule engine; violations are structurally impossible, not discouraged by prompting.
3. **Idempotency everywhere**: duplicate webhooks and double-executes provably cannot double-act (DB constraints, not discipline).
4. **Honest simulation boundary**: real Razorpay test-mode integration where possible (payment links, webhooks, signature verification); clearly-labeled simulator where test mode cannot act (server-side token charges).
5. **Evaluation harness**: seeded synthetic dataset with ground truth → batch runner → metrics report computed from the database.

## 8. What evaluators likely care about (predicted rubric)

1. Does money movement happen? Is it gated? *(safety)*
2. Can they replay a batch and see consistent numbers? *(measurability)*
3. Can they trace one case end-to-end? *(explainability/audit)*
4. What happens when the LLM is down / returns garbage? *(graceful failure)*
5. Is the Razorpay integration real or decorative? *(integration depth)*
6. Would this survive contact with production traffic? *(engineering maturity)*

## 9. Measurable outcomes we will demonstrate

From actual execution only:

- Total cases processed, revenue at risk (₹)
- Recovered cases, recovered revenue (₹), recovery rate, amount-recovery rate
- Escalations created, actions blocked by policy
- Policy violations = 0, duplicate financial actions = 0 (asserted, not claimed)
- Agent decision accuracy vs ground-truth labels in the synthetic dataset
- Mean time-to-recovery; mean agent iterations; LLM fallback rate

## 10. Credibility as an internship-level engineering project

This project demonstrates, concretely:

- Event-driven ingestion with HMAC-verified webhooks and idempotency keys
- Explicit finite-state machine for a money-touching workflow
- Tool-calling agent with schema validation, iteration caps, and timeouts
- Policy-as-code guardrails with full decision logging
- Port/adapter integration (real gateway vs simulator behind one interface)
- Reproducible evaluation framework with ground truth
- Structured observability: every case reconstructable from logs + DB

These are staff-engineer concerns executed at prototype scale — exactly the story an internship candidate wants to tell.

---

## Challenged assumptions (per instructions)

| # | Assumption in the brief | Verdict | Correction applied |
|---|---|---|---|
| A1 | "Retry payment" is a simple API call | **Wrong** | Razorpay has no public single-call "retry this failed payment" API for arbitrary one-time payments. Re-charging requires a saved token/mandate (activation-gated) or customer participation. Design: token-charge executor behind a port (simulated in buildathon) + **real Payment Links** for customer-directed recovery. See RAZORPAY_INTEGRATION.md. |
| A2 | Test mode behaves like live mode | **Partially wrong** | Test mode sends no real SMS/email for payment links; card tokens valid only ~3 days for subsequent debits; mock bank page drives success/failure. Notification layer is an outbox marked SIMULATED. |
| A3 | An ML model should score risk | **Unnecessary** | No training data exists at hackathon scale. Deterministic weighted scoring + LLM reasoning hybrid is more explainable and honest. |
| A4 | All seven example directions are buildable | **Not in time budget** | One excellent workflow (failed-payment recovery incl. subscription-style sequencing) beats five shallow ones. |
| A5 | Webhooks are reliable exactly-once | **Wrong** | Razorpay documents at-least-once delivery and out-of-order sequences (e.g., `payment.failed` then `payment.captured` for the same transaction via late authorization/user retry). Idempotent consumer + pre-action state re-check are mandatory. |
