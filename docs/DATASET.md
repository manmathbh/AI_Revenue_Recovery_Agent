# DATASET.md — Reproducible synthetic recovery dataset

## 1. Purpose

Prove measured recovery across a batch. The dataset is **seeded, versioned, and ground-truthed** so every metric (recovery rate, decision accuracy) is computed against known reality — never fabricated.

## 2. Generator

`scripts/generate_dataset.py --seed 42 --size 120 --out data/dataset_v1.jsonl`

- Python `random.Random(seed)` + fixed scenario weights → byte-identical output per seed.
- Output: JSONL of webhook-equivalent events (exact Razorpay payload schema incl. error fields) + a parallel ground-truth file.
- Committed to repo (`data/`) so judges can diff runs; regeneration documented.

## 3. Scenario mix (120 cases)

| # | Scenario | Count | Error fields | Ground truth: diagnosis | Recoverable? | Expected strategy |
|---|---|---|---|---|---|---|
| S01 | Insufficient funds, good customer | 22 | `error_source=bank, error_reason=insufficient_funds` | INSUFFICIENT_FUNDS | yes (~65%) | S2 delayed retry |
| S02 | Network/gateway transient | 14 | `error_source=network, error_reason=gateway_error` | NETWORK_INFRA | yes (~80%) | S1 immediate retry |
| S03 | Authentication failed / wrong PIN | 12 | `error_source=customer, error_reason=authentication_failed` | CUSTOMER_AUTH_REQUIRED | yes (~45%) | S3 notify+link |
| S04 | Expired/invalid card, no token | 10 | `error_source=bank, error_reason=card_expired` | INSTRUMENT_INVALID | no | S3 notify(update method)→S6 stop |
| S05 | Repeated failure (2 prior attempts) | 10 | mixed | varies | ~25% | S5 escalation |
| S06 | High-value ≥ ₹25,000 | 8 | mixed | varies | gated | S5 human approval |
| S07 | Bank downtime window | 8 | downtime active flag | BANK_DOWNTIME | after resolve | WAIT→S1 |
| S08 | Self-healed (late auth/user retry) | 8 | followed by captured | DUPLICATE_SELF_HEALED | already recovered | P02 stop |
| S09 | Duplicate webhook delivery ×2–3 | 8 | same event id repeated | — | must not double-act | idempotency |
| S10 | Unknown/garbled failure | 6 | conflicting fields | UNKNOWN | low conf | S5 escalation |
| S11 | Low-value stale (>48h old) | 14 | aged timestamps | varies | decayed | S6 stop / LOW priority |

Recoverable share ≈ 55–60% by construction → honest headline recovery rate lands in that neighborhood *if the agent behaves correctly*; underperforming strategies show up as real misses. Amounts drawn from a log-normal-ish distribution ₹299–₹2,50,000; customers sampled from a pool with tenure/LTV/token attributes so scoring has signal.

## 4. Ground truth schema

```json
{
  "case_key": "S01-007",
  "expected_diagnosis": "INSUFFICIENT_FUNDS",
  "expected_strategy": "S2_DELAYED_RETRY",
  "recoverable": true,
  "simulated_capture_probability": 0.65,
  "notes": "repeat customer, salary cycle"
}
```

The simulator consults `simulated_capture_probability` so batch outcomes are reproducible per seed while still being non-trivial.

## 5. Loading & lifecycle

`scripts/load_dataset.py` posts each event through the SAME ingestion path as live webhooks (signature attached using dev secret). Batch runner then drives cases to terminal states (`auto_advance=true` fast-forwards cooldowns/TTLs in simulated clock mode) and writes `eval_runs`.

## 6. Size justification

120 ≥ required 100; large enough for stable percentages at scenario granularity (each scenario n≥6), small enough for a sub-3-minute judged batch run with the LLM in the loop (≈2–4s/case).
