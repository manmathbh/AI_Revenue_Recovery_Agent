# IMPLEMENTATION_ROADMAP.md — 16 phases, each independently verifiable

> Estimate: ~10–12 focused working days solo. Phases are ordered by dependency; P0–P9 produce the judged system, P10–P15 harden it.

### Phase 0 — Planning (done)
Docs complete. Exit: this repository state.

### Phase 1 — Repository & tooling skeleton
Files: `pyproject.toml`, `docker-compose.yml` (postgres+api+worker+dashboard), `.env.example`, `Makefile`, `README.md`, CI workflow, ruff/mypy configs, pre-commit.
Tasks: compose boots; `/healthz` returns db-up. Tests: health smoke.
Accept: fresh clone → `make dev` → green health in ≤5 min. Risk: none.

### Phase 2 — Database core
Files: `alembic/versions/0001_initial.py`, `app/db/models.py`, enums, factories.
Tasks: all 13 tables + constraints/indexes from DATA_MODEL.md; FSM transition validator.
Tests: migration up/down; constraint violations raise; transition table completeness.
Accept: pytest green against real PG. Demo milestone: schema diagram matches reality.

### Phase 3 — Razorpay adapter + webhook ingestion
Files: `app/integrations/razorpay.py`, `app/api/webhooks.py`, signature util, `webhook_events` ledger.
Tasks: HMAC verify raw body; event dedupe; payment.failed/captured handlers create/update entities+cases; fetch_payment client with timeout/retry/breaker.
Tests: integration set §2 (signature, dup, out-of-order).
Accept: dashboard "send test webhook" creates a case. **Risk: webhook tunneling locally** — mitigation: synthetic injection endpoint + ngrok docs.

### Phase 4 — Synthetic dataset
Files: `scripts/generate_dataset.py`, `scripts/load_dataset.py`, `data/dataset_v1.jsonl` committed.
Tests: determinism (same seed ⇒ same bytes); ground-truth consistency checks.
Accept: 120 cases loaded via real ingestion path; scenario counts match DATASET.md.

### Phase 5 — Risk engine
Files: `app/risk/engine.py`.
Tests: unit suite from TESTING.md §1 (arithmetic golden values).
Accept: scores visible on cases; band edges exact.

### Phase 6 — Agent orchestrator + tools
Files: `app/agent/{loop.py,tools.py,schemas.py,prompts.py}`, `FakeLLM` for tests, provider client.
Tasks: bounded loop, tool registry (read tools), DecisionRecord validation, strike/timeout/fallback ladder, reasoning_trace persistence.
Tests: scripted transcripts; iteration cap; invalid-tool strikes; injection probes.
Accept: single case runs end-to-end to DIAGNOSED with persisted decision. **Risk: LLM flakiness** — FakeLLM keeps tests deterministic; live eval separate.

### Phase 7 — Policy engine
Files: `app/policy/{engine.py,rules.py,config.py}`.
Tests: full rule matrix (~120 cases) + property test (no executor call without ALLOW).
Accept: verdicts + full traces on cases; config seeded.

### Phase 8 — Executors + recovery workflows
Files: `app/executors/{retry_charge.py,recovery_link.py,notify.py,escalation.py}`, worker loop (claim/SLA/TTL), strategy fallback table, escalation approval API.
Tests: e2e happy path; policy-rejection path; high-value gate; duplicate-race.
Accept: cases reach RECOVERED / ESCALATED / BLOCKED correctly without human help. **This is the milestone that makes the product real.**

### Phase 9 — Verification service
Files: `app/verification/{service.py,sweeper.py}`.
Tasks: captured-webhook matching by order/reference_id; polling reconciliation; self-heal detection; recovered_amount writes restricted to verifier role.
Tests: out-of-order capture; late capture after TTL window; double-capture idempotent.
Accept: every RECOVERED case has an observation record.

### Phase 10 — Evaluation harness
Files: `scripts/evaluate.py`, baseline runners B0/B1/B2, report generator (`reports/*.md|json`), assertions.
Tests: reproducibility (two seeds identical); assertion fires on injected violation fixture.
Accept: `make evaluate SEED=42` produces the full report incl. baselines.

### Phase 11 — Dashboard
Files: Next.js app per DEMO_UI.md; generated API types.
Accept: all five views live-polling; batch run visible end-to-end; SIMULATED badges present.

### Phase 12 — Failure drills
Tasks: execute FAILURE_HANDLING scenarios as scripts/tests (LLM down, RZP breaker, kill-worker, replay duplicates).
Accept: chaos e2e suite green; degradation chips work.

### Phase 13 — Security pass
Tasks: gitleaks, redaction tests, rate limits, authz tests, audit tamper test, SECURITY checklist sign-off.

### Phase 14 — Demo rehearsal
Tasks: DEMO_PLAN dry-run ×3 with timer; screen-recording fallback; seed reset script (`make demo-reset`) for instant clean state between judge sessions.

### Phase 15 — Final polish
README with architecture GIF + quickstart; docs index; code comments on tricky bits (idempotency, FSM); tag `v1.0`; freeze.

## Critical path

2 → 3 → {4,5} → 6 → 7 → 8 → 9 → 10. Dashboard (11) can parallel-track from Phase 8 onward using a second person or evenings.
