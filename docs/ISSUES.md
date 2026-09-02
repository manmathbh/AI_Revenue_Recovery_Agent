# ISSUES.md — Engineering backlog

Format: ID · Title · Why · Depends · Tasks · Acceptance · Tests · Priority · Complexity (S/M/L)

## P0 — Must have (system is not credible without these)

**REC-001 · Repo scaffold + compose + CI**
Why: everything depends on a reproducible dev environment. Dep: —. Tasks: pyproject, compose, Makefile, ruff/mypy, Actions. Accept: `make dev` green from clean clone. Tests: health smoke. P0 · S

**REC-002 · Database schema + migrations**
Why: the data model IS the audit story. Dep: REC-001. Tasks: 13 tables, enums, constraints, indexes, FSM validator, factories. Accept: migration up/down; constraint tests pass. Tests: unit+integration. P0 · M

**REC-003 · Webhook ingestion with HMAC + idempotency ledger**
Why: entry point for all truth; first safety layer. Dep: REC-002. Tasks: raw-body HMAC, event dedupe, entity upsert, case creation, rate limit. Accept: forged sig 401; duplicate no-op; out-of-order handled. Tests: integration §2. P0 · M

**REC-004 · Razorpay adapter (fetch payment, create payment link) + circuit breaker**
Why: real integration credibility. Dep: REC-002. Tasks: httpx client, timeouts/retries/breaker, port interface + SimulatedGatewayAdapter. Accept: mocked-HTTP suite green; breaker opens/closes. Tests: respx suite. P0 · M

**REC-005 · Case FSM + worker loop (claim/SLA/TTL)**
Why: bounded lifecycle engine. Dep: REC-002. Tasks: transition service, SKIP LOCKED claim, TTL sweeper. Accept: illegal transitions raise; double-claim impossible. Tests: FSM unit + concurrency test. P0 · M

**REC-006 · Risk scoring engine**
Why: prioritization + judge-visible arithmetic. Dep: REC-002. Tasks: components, banding, recompute hooks. Accept: golden-value unit tests pass. P0 · S

**REC-007 · Agent orchestrator: loop, tools, DecisionRecord, fallback ladder**
Why: the AI core — must be bounded and safe. Dep: REC-005, REC-006. Tasks: tool registry+schemas, prompts, strikes/timeouts, FakeLLM, trace persistence. Accept: scripted transcripts pass; cap/timeout/fallback proven. Tests: agent suite. P0 · L

**REC-008 · Policy engine P01–P14 with full traces**
Why: the differentiator. Dep: REC-007. Tasks: rule evaluator, config table, escalation routing. Accept: rule matrix green; property test passes. P0 · M

**REC-009 · Executors (retry/link/notify/escalate) + idempotent action records**
Why: where money would move. Dep: REC-008, REC-004. Tasks: pre-action live checks, unique attempt keys, mode badges, outbox. Accept: e2e happy path + rejection path green. P0 · L

**REC-010 · Verification service (webhook match, polling, self-heal)**
Why: recovery claims must be observed, not asserted. Dep: REC-009. Accept: all RECOVERED cases have observation rows; self-heal path tested. P0 · M

**REC-011 · Synthetic dataset generator + loader**
Why: measurable batch. Dep: REC-003. Tasks: seeded generator, ground truth, load via ingestion. Accept: determinism byte-test; 120 cases loaded. P0 · M

**REC-012 · Evaluation runner + assertions + baselines B0–B2**
Why: the numbers slide. Dep: REC-010, REC-011. Accept: `make evaluate` emits report; violations/duplicates assert 0; baselines chart data. P0 · M

## P1 — Important (judged demo quality)

**REC-013 · Dashboard: Overview + Cases + Case Detail** (Dep: REC-009) live KPIs, decision/policy cards, timeline. Accept: DEMO_UI parity. P1 · L
**REC-014 · Escalation approval UI + API decide endpoint** (Dep: REC-009). P1 · S
**REC-015 · Evaluation view + baseline comparison chart** (Dep: REC-012, REC-013). P1 · S
**REC-016 · Downtime-aware suppression via payment.downtime.* webhooks** (P09 wiring, dataset S07 activation). Why: real documented Razorpay signal → strong differentiator. P1 · S
**REC-017 · Failure drills scripted as tests** (LLM down, breaker, kill-worker, replay). P1 · M
**REC-018 · Observability pack**: structlog catalog, health chips, alert conditions. P1 · S

## P2 — Nice to have

**REC-019 · Audit viewer page with chain validation display.** P2 · S
**REC-020 · Merchant policy-config editor in dashboard (audited changes).** P2 · M
**REC-021 · Subscription-dunning preset profile** (same engine, different defaults). P2 · M
**REC-022 · Decision replay sandbox** ("what if confidence were higher?"). P2 · M
**REC-023 · Hinglish notification copy variant (text only).** P2 · S

## P3 — Stretch

**REC-024 · OpenTelemetry tracing export.** P3 · M
**REC-025 · Multi-worker horizontal scaling proof (docker scale).** P3 · S
**REC-026 · Public demo environment (tunnel) with reset button.** P3 · M
**REC-027 · Voice/Hinglish IVR spike** (explicitly cut unless everything else done). P3 · L

Sequencing note: P0 issues map 1:1 to roadmap phases 1–10; do not start P2 before REC-012 is green.
