# API_DESIGN.md — Backend API surface

Base: `http://localhost:8000/api/v1` · JSON only · errors follow RFC 7807-style `{type, title, status, detail, instance, errors?}`.

Auth: two schemes.
- **Admin/Dashboard**: `Authorization: Bearer $ADMIN_API_KEY` (env).
- **Webhook**: HMAC-SHA256 signature header (see below) — no bearer.

Idempotency: all POSTs that mutate accept `Idempotency-Key` header; server stores key→response for 24h; replay returns the original response with `Idempotent-Replay: true`.

## Endpoints

### Health
`GET /healthz` → `200 {status:"ok", db:"up", llm:"configured", rzp:"test"}` (no auth).

### Webhooks
```
POST /api/v1/webhooks/razorpay
Headers: X-Razorpay-Signature: hmac_sha256_hex(raw_body, WEBHOOK_SECRET)
Body: raw Razorpay event JSON (payment.failed | payment.captured | payment.downtime.*)
```
Processing order: read raw body → verify signature (fail → `401`, log, no state change) → INSERT webhook_events by unique event_id (conflict → `200 {received:true, duplicate:true}` no-op) → upsert entities → create/advance case → `202 {received:true, case_ref?}`.
Never 500 on business errors after acceptance (Razorpay retries on non-2xx); internal failures return 202 and park work in DB for the worker.

### Cases
```
GET /api/v1/cases?status=&risk_band=&min_amount_minor=&limit=&cursor=
→ 200 {items:[CaseSummary], next_cursor}
CaseSummary: {case_ref, customer_masked, amount_minor, currency, method,
              diagnosis_class?, risk_score, risk_band, strategy_id?,
              status, recovered_amount_minor, created_at}

GET /api/v1/cases/{case_ref}
→ 200 CaseDetail: summary + payment + attempts[] + decisions[] (with rationale)
   + policy_results[] (rule trace) + actions[] + escalations[] + timeline[](audit)

POST /api/v1/cases/{case_ref}/analyze        Auth: admin
→ re-runs agent+policy for an existing case (demo/debug). Idempotency-Key honored.
→ 202 {case_ref, status}

POST /api/v1/cases/{case_ref}/execute        Auth: admin   Headers: Idempotency-Key REQUIRED
Body: {} (executes current APPROVED plan)
→ 202 {case_ref, action_ref, execution_mode}
Errors: 409 if status not APPROVED; 422 if policy verdict changed to BLOCK on re-check.
```

### Batch / evaluation
```
POST /api/v1/batch/runs      Auth: admin
Body: {dataset_seed?: int=42, size?: int=120, scenario_mix?: "default", auto_advance?: bool=true}
→ 202 {run_ref}                       (worker processes; dashboard polls)

GET  /api/v1/batch/runs/{run_ref}
→ 200 {status: RUNNING|COMPLETE, progress:{processed,total}, report?: EvalReport}

GET  /api/v1/metrics/summary
→ 200 {revenue_at_risk_minor, recovered_minor, recovery_rate, amount_rate,
       active_cases, escalated_open, blocked_total, self_healed_total,
       policy_violations: 0, duplicate_actions: 0}     ← computed live from DB

GET  /api/v1/metrics/evaluation/{run_ref} → 200 full EvalReport (see EVALUATION.md)
```

### Escalations
```
GET  /api/v1/escalations?status=OPEN
POST /api/v1/escalations/{escalation_ref}/decide   Auth: admin   Idempotency-Key REQUIRED
Body: {"decision":"APPROVED"|"REJECTED", "note":"string≤280"}
→ 200 {escalation_ref, status, case_status}
409 if already decided. Approval re-enters case flow at POLICY_CHECK per FSM.
```

### Audit
```
GET /api/v1/audit/cases/{case_ref}
→ 200 {events:[{at, actor, event_type, detail, event_hash, prev_event_hash}], chain_valid: true}
```

## Status codes & error taxonomy

| Code | Used for |
|---|---|
| 200/202 | success / accepted-for-async-processing |
| 400 | malformed JSON/body |
| 401 | bad bearer or bad webhook signature |
| 404 | unknown case/action/run |
| 409 | illegal FSM transition, already-decided escalation, duplicate with different payload |
| 422 | schema validation failure (pydantic detail attached) |
| 429 | rate limit (webhook endpoint: token bucket per source IP) |
| 500 | unexpected — alerting fires; webhook path avoids this post-acceptance |

## Validation rules

- All bodies pydantic-validated (`extra="forbid"`); amounts must be positive ints ≤ ₹1Cr (buildathon sanity cap); enums closed.
- `case_ref` format `^RC-\d{6}$`; unknown refs are 404 not 500.
- Webhook body size cap 256KB; timestamp skew check (>10-min-old events logged as STALE, still processed idempotently).

## OpenAPI

FastAPI auto-generates `/docs`; the Next.js dashboard consumes generated types from the OpenAPI schema (single source of truth).
