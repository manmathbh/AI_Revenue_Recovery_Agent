# MVP_SCOPE.md — Choosing the strongest workflow

## 1. Candidate comparison

Scored 1–5 (5 = best for us). Weights reflect buildathon judging emphasis.

| Criterion (weight) | A. Failed payment recovery | B. Checkout abandonment | C. Failed subscription | D. B2B receivables |
|---|---|---|---|---|
| Implementation complexity (×2) | 4 (webhook + engine) | 3 (needs session data) | 4 (same engine as A) | 1 (new domain: invoices, terms) |
| Razorpay relevance (×3) | 5 (`payment.failed`, error fields) | 3 (Magic Checkout overlaps) | 5 (Subscriptions core) | 2 (no invoice API anchor) |
| Demo value (×2) | 5 (live fail→recover story) | 3 | 4 | 3 |
| Measurable recovery (×3) | 5 (₹ per case, verified capture) | 3 (attribution fuzzy) | 5 | 3 |
| AI-agent value (×2) | 5 (diagnosis genuinely needs reasoning over messy signals) | 3 (mostly templated reminders) | 4 | 3 |
| API integration potential (×2) | 5 (payments+links+webhooks+downtime) | 3 | 4 | 2 |
| Safety concerns manageable (×2) | 4 (bounded retries, caps) | 4 | 4 | 3 (comms compliance riskier) |
| Time required (×2) | 4 (~fits) | 3 | 4 | 1 (too big) |
| Resume value (×1) | 5 | 3 | 4 | 3 |
| **Weighted total** | **~68** | ~40 | ~60 | ~29 |

## 2. Selection

> **MVP = Workflow A: Failed Payment Recovery**, with **C folded in as a policy pattern** (mandate-style retry sequencing with cooldowns and expiry is the same engine with different parameters), and **downtime-aware suppression** from scenario 5.

Rationale:

- It exercises the **entire required loop** (detect → diagnose → decide → gate → act → verify → measure → audit → escalate) with real Razorpay artifacts at every step.
- `payment.failed` webhooks carry structured diagnosis inputs (`error_code`, `error_source`, `error_step`, `error_reason`) — the agent reasons over real signal, not invented data.
- Recovery verification closes on a REAL `payment.captured` webhook or a fetched payment object — recovery claims are provable.
- One engine, one state machine, one evaluation harness. Depth over breadth.

## 3. In scope (MVP)

1. Webhook ingestion: `payment.failed`, `payment.captured`, `payment.downtime.started/resolved` — HMAC-SHA256 verified, idempotent.
2. Deterministic revenue-risk scoring and prioritization.
3. LLM agent (bounded ReAct loop, whitelisted read tools) producing: failure diagnosis class, strategy proposal, confidence, human-readable rationale.
4. Deterministic strategy fallback when LLM unavailable/degraded.
5. Policy/guardrail engine: retry caps, cooldowns, amount thresholds, confidence floor, contact caps, duplicate-action prevention, already-recovered stop.
6. Action executors:
   - `retry_charge` — token/mandate charge via gateway port; **simulated outcome** in buildathon (clearly labeled).
   - `send_payment_link` — **real Razorpay test-mode Payment Links API**.
   - `notify_customer` — outbox pattern (SIMULATED channel).
   - `create_escalation` — internal queue + dashboard approval action.
7. Verification: webhook-driven capture detection + polling reconciliation; self-heal detection (customer already retried successfully).
8. State machine with terminal states incl. BLOCKED / ESCALATED / EXPIRED.
9. Synthetic dataset (≥120 cases, seeded, ground-truthed) + batch runner + metrics report.
10. Dashboard: overview KPIs, case list, case detail with decision/policy/audit timeline, evaluation view.

## 4. Out of scope (MVP)

- Checkout abandonment funnel, B2B invoicing/receivables, voice/Hinglish interface
- Real SMS/email delivery (outbox only)
- Multi-tenant auth beyond a single demo merchant + admin key
- ML training, vector DB, RAG
- Kubernetes/multi-service deployment

## 5. Stretch goals (only after P0 complete)

- S1: Subscription dunning preset (policy profile reusing the same engine)
- S2: Downtime-aware retry suppression using `payment.downtime.*` webhooks *(promoted to P1 if time allows — cheap and high wow-factor)*
- S3: Decision replay button ("what would policy do if confidence were higher?")
- S4: Hinglish notification copy variant (text only, no voice)

## 6. Success criteria for the MVP

A judge can, in under 5 minutes, without help:
1. Trigger/view a failed payment case,
2. Watch the agent diagnose and propose,
3. See policy approve/block/escalate deterministically,
4. See a verified recovery increment ₹ on the dashboard,
5. Replay the 120-case batch and get a consistent metrics report with zero violations/duplicates.
