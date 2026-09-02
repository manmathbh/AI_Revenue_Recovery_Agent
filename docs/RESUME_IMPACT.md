# RESUME_IMPACT.md — How this reads on an internship resume

## One-liner

**Recoup — AI Revenue Recovery Agent (Razorpay Buildathon)**: policy-gated LLM agent that detects failed payments, diagnoses root causes, executes bounded recovery actions via Razorpay test APIs, and reports verified rupees recovered with a zero-violation audit trail.

## Bullet templates (fill ONLY with real measured numbers from `reports/`)

- Designed a **bounded tool-calling agent** (ReAct-style, ≤6 iterations, schema-validated outputs) whose every financial action passes a deterministic 14-rule policy engine — **0 policy violations and 0 duplicate actions across N-case batch runs**.
- Built an **event-driven recovery pipeline** on FastAPI + PostgreSQL: HMAC-verified Razorpay webhooks, idempotency at 5 layers (event ledger, unique action keys, idempotency keys, pre-action state re-check, DB constraints), explicit finite-state machine for money-touching workflows.
- Implemented **verified revenue attribution**: recoveries counted only from observed `payment.captured` events, separating agent-driven recovery from customer self-heals; batch evaluation harness with seeded ground truth and do-nothing/naive/rules-only baselines.
- Created an **honest simulation boundary**: real Razorpay test-mode integration (Payment Links, webhooks) behind a gateway port, with clearly labeled simulated token-charge executor where live APIs are activation-gated.
- Shipped a decision-explainability layer: per-case rationale, full rule-by-rule policy traces, and hash-chained append-only audit logs.

## Skills evidenced (interview talking points)

| Area | Concrete artifact to point at |
|---|---|
| Agentic AI | bounded loop, strike counting, fallback ladder, hallucination probes |
| FinTech integration | webhook signature verification, payment lifecycle handling, late-auth edge case |
| Backend architecture | modular monolith, ports/adapters, outbox pattern, worker leases |
| Reliability | circuit breaker, chaos drills, crash-consistent transitions |
| Safety engineering | policy-as-code, human-in-the-loop gates, stopping rules |
| Evaluation engineering | reproducible seeds, hard assertions, baseline comparisons |

## Integrity rule

Never claim production deployment, real money processed, or accuracy numbers that didn't come from `reports/*.json`. Interviewers probe exactly there — the honest simulation story is itself a strength ("I know exactly where the boundary between real and simulated is, and I made it visible").
