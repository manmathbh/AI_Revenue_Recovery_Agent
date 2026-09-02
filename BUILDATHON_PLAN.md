# BUILDATHON_PLAN.md — Recoup: AI Revenue Recovery Agent (master summary)

> **Track 03 — AI Revenue Recovery · Razorpay Buildathon**
> Full design lives in `docs/` (24 documents). This is the executive layer.

## 1. Project name
**Recoup** — the bounded AI revenue recovery agent for Razorpay merchants.

## 2. One-line pitch
Recoup detects failed payments, diagnoses why they failed, executes policy-gated recovery actions through Razorpay, and proves every rupee recovered with a zero-violation audit trail.

## 3. Problem
Merchants silently lose lakhs monthly to recoverable payment failures. Today's options — ignore, or blast generic emails — lack diagnosis, prioritization, safety, and measurement.

## 4. Solution
An event-driven agent pipeline: **Detect → Understand → Diagnose → Decide → Validate policy → Execute bounded action → Verify → Measure → Audit → Escalate**. The LLM is the diagnostician; deterministic systems own money, state, and truth.

## 5. Target users
Revenue/ops leads at Indian mid-market online businesses (D2C, subscriptions) running on Razorpay.

## 6. MVP
Failed-payment recovery end-to-end (subscription-style retry sequencing folded in as a policy pattern). Out: receivables, abandonment funnels, voice. See `MVP_SCOPE.md`.

## 7. Architecture
Modular monolith (FastAPI + worker loops) + PostgreSQL + Next.js dashboard. Components: Ingestion (HMAC+idempotent), Case FSM, Risk Engine, Agent Orchestrator, Policy Engine, Action Executor behind a GatewayPort (real Razorpay adapter + labeled simulator), Verification Service, append-only audit, eval runner. Diagram: `ARCHITECTURE.md`.

## 8. Agent architecture
Bounded ReAct loop (≤6 iterations, 20s timeout, 2-strike invalid-call limit), whitelisted read tools + one proposal tool emitting a schema-validated DecisionRecord (diagnosis class, strategy S1–S6, confidence, ≤400-char rationale). Degradation ladder ends in a deterministic strategy table. Hallucination defenses: state read only from DB/Razorpay, recovery only from observed capture, injection-hardened context packs. `AGENT_DESIGN.md`.

## 9. Guardrails
14 ordered deterministic rules (P01–P14): state eligibility, already-recovered stop, max 3 retries, cooldowns 30m→8h, ₹25,000 auto-approval ceiling, 0.60 confidence floor, duplicate-action prevention, contact caps, downtime hold, TTL 72h, param sanity, audit-before-execute. Verdicts ALLOW/BLOCK/ESCALATE/WAIT with full rule traces. `GUARDRAILS.md`.

## 10. Razorpay integration
REAL on test keys: `payment.failed/captured` webhooks (HMAC-SHA256 raw-body verified), Payment Links create/notify, payment fetch, downtime webhooks. SIMULATED (labeled): token-charge retries (activation-gated upstream; no public retry API exists). Capability matrix + limits register: `RAZORPAY_INTEGRATION.md`.

## 11. Data model
13 tables: merchants, customers, payments, recovery_cases, agent_decisions, policy_decisions, recovery_actions, notifications(outbox), escalations, webhook_events(idempotency ledger), audit_events(hash-chained), eval_runs(+results). Money in paise; unique constraints make duplicate actions structurally impossible. `DATA_MODEL.md`.

## 12. Evaluation metrics
From DB only, hard-asserted: recovered ₹ & rates vs seeded ground truth, self-heal attribution, policy violations = 0, duplicate actions = 0, diagnosis accuracy ≥85% target, fallback rate, MTTR — plus do-nothing / naive-retry / rules-only baselines quantifying the agent's marginal value. `EVALUATION.md`, `DATASET.md` (120 cases, seed 42).

## 13. Demo scenarios
① Live real-link recovery with counter tick ★ ② Policy blocks exhausted retries → human approves ③ ₹75k auto-gated to approval ④ Duplicate webhook attack absorbed ⑤ Batch report with zeros + baselines. Resilience bonus: kill-the-LLM fallback live. `DEMO_PLAN.md`.

## 14. Technology stack
Python 3.12 · FastAPI · Pydantic v2 · SQLAlchemy 2/Alembic · httpx · structlog · PostgreSQL 16 · Next.js 14/Tailwind · OpenAI-compatible tool-calling LLM (provider-swappable) · pytest/ruff/mypy · docker compose. No Redis/Celery/vector-DB/k8s. `TECH_STACK.md`.

## 15. Repository structure
```
AI_Revenue_Recovery_Agent/
├── BUILDATHON_PLAN.md          ← you are here
├── docs/                       ← 25 planning docs
├── backend/app/
│   ├── api/          (webhooks, cases, batch, escalations, metrics, audit)
│   ├── domain/       (fsm, risk/, policy/, strategies)
│   ├── agent/        (loop, tools, schemas, prompts, fake_llm)
│   ├── executors/    (retry_charge, recovery_link, notify, escalation)
│   ├── verification/ (service, sweeper)
│   ├── integrations/ (razorpay adapter, simulated gateway, outbox)
│   ├── db/           (models, migrations via alembic/)
│   └── obs/          (logging, health)
├── frontend/                   (Next.js dashboard)
├── scripts/                    (generate_dataset, load_dataset, evaluate, replay_webhook, demo_reset)
├── data/                       (dataset_v1.jsonl + ground truth, committed)
├── tests/{unit,integration,e2e,agent_eval}
├── reports/                    (generated run reports)
├── docker-compose.yml · Makefile · .env.example · README.md
```

## 16. Development phases
0 Planning ✅ → 1 Scaffold → 2 Database → 3 Razorpay+webhooks → 4 Dataset → 5 Risk engine → 6 Agent → 7 Policy engine → 8 Executors/workflows → 9 Verification → 10 Evaluation → 11 Dashboard → 12 Failure drills → 13 Security → 14 Demo rehearsal → 15 Polish. (~10–12 days; critical path 2→3→6→7→8→9→10.) `IMPLEMENTATION_ROADMAP.md`.

## 17. Issue roadmap
27 issues: 12×P0 (system credibility), 6×P1 (demo quality incl. downtime suppression), 5×P2, 4×P3 stretch. `ISSUES.md`.

## 18. Risks
LLM flakiness (→ FakeLLM tests, fallback ladder, recorded demo) · venue wifi kills webhooks (→ synthetic injection path, same code) · time crunch (→ P0 scope frozen at phase 10; drills/security trimmed last, HMAC+idempotency never) · "is it real?" skepticism (→ honesty badges + capability matrix rehearsed).

## 19. Differentiators
The visible policy gate ("the AI asked, the rules refused") · verified rupees from real test-mode capture · hard-asserted zero-violation evaluation with baselines · honest real-vs-simulated boundary as a feature · failure-first engineering demonstrated live. `DIFFERENTIATION.md`.

## 20. Final judging strategy
Open with the merchant pain (30s), win Demo 1 (real link → verified recovery → live counter), let Demo 2's refusal moment land the safety story, close on the batch report where violations=0 and duplicates=0 are *asserted by code*. Every skeptical question routes to an artifact: capability matrix, audit chain viewer, chaos drill. Target score ≈90/100 (`SCORECARD.md`). One-line closer: *"The LLM is the diagnostician, not the surgeon — and every rupee it claims, Razorpay confirms."*
