# ARCHITECTURE.md — System design

## 1. Shape: modular monolith, event-driven core

One deployable backend process (API + background worker loops), one Postgres, one Next.js dashboard. Module boundaries are enforced in code so extraction into services later is mechanical.

```
                                ┌─────────────────────────────────────────────────────────┐
                                │                      DASHBOARD (Next.js)                │
                                │   Overview │ Cases │ Case Detail │ Audit │ Evaluation   │
                                └───────────────▲─────────────────────────────────────────┘
                                                │ REST /api/v1 (JSON)
┌───────────────────────────────────────────────┴──────────────────────────────────────────┐
│                            BACKEND — FastAPI (modular monolith)                          │
│                                                                                          │
│  ┌──────────────┐   ┌──────────────┐   ┌───────────────┐   ┌──────────────────────────┐  │
│  │ Ingestion    │   │ Recovery     │   │ Agent         │   │ Policy Engine            │  │
│  │ /webhooks    ├──▶│ Case Service │──▶│ Orchestrator  │──▶│ (pure functions, ordered │  │
│  │ HMAC verify  │   │ state machine│   │ bounded ReAct │   │ rules P01–P14)           │  │
│  │ idempotency  │   │ + risk score │   │ + tools       │   └───────────┬──────────────┘  │
│  └──────────────┘   └──────▲───────┘   └───────┬───────┘               │ ALLOW/BLOCK/    │
│                            │                   │ tools                 │ ESCALATE/WAIT   │
│  ┌─────────────────────────┴───┐   ┌───────────▼───────────────────────▼──────────────┐   │
│  │ Verification Service        │   │ Action Executor                                  │   │
│  │ webhook capture detection   │◀──│ retry_charge │ send_recovery_link │ notify │ esc  │   │
│  │ polling reconciliation      │   └───────────┬──────────────────────────────────────┘   │
│  │ self-heal detection         │               │ ports                                    │
│  └─────────────────────────────┘   ┌───────────▼──────────────────────────────────────┐   │
│                                    │ Gateway Adapters                                 │   │
│  ┌──────────────┐   ┌──────────────┐│  RazorpayAdapter (REAL test-mode REST+links)     │   │
│  │ Metrics &    │   │ Audit Log    ││  SimulatedGatewayAdapter (token charges, labeled)│   │
│  │ Eval Runner  │   │ (append-only)││  OutboxNotifier (SIMULATED channels)             │   │
│  └──────┬───────┘   └──────┬───────┘└───────────┬──────────────────────────────────────┘   │
└─────────┼──────────────────┼────────────────────┼──────────────────────────────────────────┘
          ▼                  ▼                    ▼
┌─────────────────────────────────────────────────────────────┐   ┌──────────────────────┐
│                     PostgreSQL 16                           │   │  LLM Provider        │
│  cases · payments · customers · decisions · policy_results  │   │  (OpenAI-compatible  │
│  actions · notifications · escalations · webhook_events     │   │   tool calling,      │
│  audit_events · eval_runs · eval_case_results               │   │   swappable via env) │
└─────────────────────────────────────────────────────────────┘   └──────────────────────┘
          ▲
          │ payment.failed / payment.captured / payment.downtime.* (HMAC-SHA256 signed)
┌─────────┴────────────┐
│  RAZORPAY TEST MODE  │  Orders · Payments fetch · Payment Links (real) · Webhooks (real)
└──────────────────────┘
```

## 2. Component rationale

| Component | Exists because | Alternative rejected | Complexity | In MVP |
|---|---|---|---|---|
| **Ingestion** | Single entry point enforcing HMAC verification + idempotency before anything touches the DB | Direct DB writes from webhooks (unsafe) | Low | ✅ |
| **Case Service + FSM** | Money workflow must have explicit legal states/transitions, not ad-hoc flags | Free-form status strings | Medium | ✅ |
| **Risk Engine** | Deterministic prioritization; judges can inspect arithmetic | ML model (no data) | Low | ✅ |
| **Agent Orchestrator** | Bounded observe→reason→act loop over whitelisted tools; produces structured decision | Raw prompt → free text | Medium-High | ✅ |
| **Policy Engine** | Hard gate between agent and money; pure functions = trivially testable | Prompt-based guardrails ("please be safe") | Low-Medium | ✅ |
| **Action Executor** | One choke point for side effects; enforces idempotency keys + labels SIMULATED vs REAL | Tools calling gateway directly | Medium | ✅ |
| **Verification Service** | Recovery claims must come from Razorpay state, not the agent | Trusting executor return codes | Medium | ✅ |
| **Audit Log** | Append-only trail per case; powers Case Detail UI | Console logs | Low | ✅ |
| **Metrics/Eval Runner** | Batch reproducibility; numbers computed from DB | Hand-counted slides | Low | ✅ |
| **Outbox Notifier** | Records exactly what would be sent without third-party dependencies | Real SMS/email vendor | Low | ✅ |
| Redis/queue | Throughput we don't have | — | — | ❌ |
| Vector DB | No corpus | — | — | ❌ |

## 3. Key flows

### Flow 1 — Failure to recovery (happy path)

```
payment.failed webhook → verify HMAC → insert webhook_events (unique ext_id)
  → upsert customer/payment → create case(DETECTED) [same DB tx]
worker claims case → ANALYZING (enrichment + risk score)
  → DIAGNOSED (agent loop: read-tools → structured decision)
  → PLANNED (strategy S2 delayed_retry, conf 0.82)
  → POLICY_CHECK (P01..P14 pass) → APPROVED
  → EXECUTING (send_recovery_link → REAL payment link created; outbox message recorded)
  → VERIFYING (awaiting payment.captured)
customer pays link (test mode) → payment.captured webhook (HMAC verified)
  → match by order/reference_id → RECOVERED, recovered_amount=amount, metrics updated
```

### Flow 2 — Policy block / escalation

```
case retry_count=3 → agent proposes S1 immediate_retry
  → POLICY_CHECK: P03 MAX_RETRIES fails → verdict BLOCK(reason=P03)
  → strategy fallback table → S5 human_escalation → AWAITING_APPROVAL → ESCALATED
```

### Flow 3 — Self-heal (documented Razorpay behavior)

```
payment.failed arrives; before acting, VERIFYING/pre-action re-check fetches payment:
status=captured (late authorization / user retried in UPI app)
  → case CLOSED as SELF_HEALED; recovered=true but intervention=none
  → counted separately in metrics (honest attribution)
```

## 4. Concurrency & consistency rules

1. Webhook handler does **verify → insert event row (unique constraint) → upsert entities → create case** in ONE transaction; duplicates die on the unique key.
2. Worker claims cases with `SELECT ... FOR UPDATE SKIP LOCKED` — safe single instance, ready for multi-worker later.
3. Every action insert carries `(case_id, action_type, attempt_no)` unique constraint — duplicate execution is a DB error, not a hope.
4. State transitions validated against the FSM table in the same transaction as the business write.
5. All times UTC; all money integer paise.

## 5. Deployment topology (demo)

`docker compose up` → postgres, api (uvicorn), worker (same image, `ROLE=worker`), dashboard. Seeded demo merchant + synthetic batch importable via `scripts/load_dataset.py`.
