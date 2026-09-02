# OBSERVABILITY.md — Every rupee explainable

## 1. Log strategy

`structlog` JSON lines, one event per meaningful step, all carrying `case_ref`, `run_id`, `trace_id` (per webhook/worker job). Example:

```json
{"ts":"2026-08-21T10:22:31Z","level":"info","event":"policy_evaluated",
 "case_ref":"RC-000042","actor":"POLICY","verdict":"ALLOW",
 "triggered_rules":[{"rule_id":"P03","passed":true},{"rule_id":"P05","passed":true}],
 "trace_id":"01J9..."}
```

Redaction processor strips secrets/PII (SECURITY.md). Logs are for debugging; the DB is the source of truth for audit.

## 2. The per-case explanation (product feature, not just logs)

Every case renders exactly the judge-friendly narrative:

```
Recovery Case: RC-000042
Detected:        payment.failed ₹4,999 · card · error_reason=insufficient_funds
Risk:            68 (HIGH)  [amount 13.6 | reversibility 20 | customer 16 | history 12 | time 6.4]
Diagnosis:       INSUFFICIENT_FUNDS (confidence 0.86) — LLM, 3 tool calls, 2 iterations
Recommendation:  S2_DELAYED_RETRY after 240m — "Repeat customer with saved token and four prior
                 successful payments; salary-cycle timing favors a delayed retry." (DEC-29382)
Policy:          ALLOW — P01✓ P02✓ P03✓ P04✓ P05✓ P06✓ P07✓ P08✓ P09✓ P10✓ P11✓ P13✓ P14✓
Action:          ACT-1180 RETRY_CHARGE attempt 2 [SIMULATED] → SUCCEEDED
Verification:    payment.captured observed (pay_... / simulated txn) at +3h41m
Recovered:       ₹4,999   Outcome: RECOVERED
Audit chain:     valid (14 events, hash-linked)
```

No raw chain-of-thought is exposed anywhere — only the structured rationale + evidence links.

## 3. Metrics

Prometheus-style counters/gauges exposed at `/metrics` (and mirrored into `eval_runs`):

- `cases_total{status}` , `recovered_amount_minor_total{mode=REAL|SIMULATED|SELF_HEAL}`
- `actions_total{type,result}`, `policy_decisions_total{verdict,rule_id}`
- `llm_calls_total{origin,fallback}`, `llm_latency_seconds` histogram
- `gateway_circuit_state`, `webhook_events_total{type,duplicate}`
- worker SLA breaches gauge

## 4. Tracing

Lightweight: `trace_id` spans ingestion → worker → agent → executor → verification via structlog bindings (no Jaeger in MVP — one process makes log correlation sufficient; document the upgrade path to OpenTelemetry).

## 5. Health & alerting surface

`/healthz` deep checks (db, llm configured, rzp reachable) + dashboard status chips. Alert conditions (log ERROR + dashboard banner): circuit open >5m, fallback rate >30%, any policy-violation assertion failure, SLA breach backlog >10.

## 6. Demo-time observability

"Follow one rupee" view = Case Detail timeline (audit_events) — the same data judges can pull via `GET /api/v1/audit/cases/{ref}` with `chain_valid:true`.
