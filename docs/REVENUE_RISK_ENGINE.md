# REVENUE_RISK_ENGINE.md — Detecting & prioritizing revenue at risk

## 1. Approach selection

| Approach | Verdict |
|---|---|
| Pure rules ("if amount > X") | Too brittle; ignores interactions |
| Trained ML model | ❌ No training data at buildathon scale; unexplainable |
| **Deterministic weighted score + banding** | ✅ Transparent arithmetic, tunable, auditable |

Detection itself is event-driven (webhooks create cases); scoring determines **priority and SLA**, not existence.

## 2. Score design (0–100, integer paise amounts, UTC times)

```
risk_score = w1·amount_component        (0–30)
           + w2·reversibility_component (0–25)
           + w3·customer_value          (0–20)
           + w4·retry_history           (0–15)
           + w5·time_sensitivity        (0–10)
```

### Components

**amount_component (0–30)** — log-scaled so ₹500 and ₹5,000 differ meaningfully but ₹5L doesn't dominate:
`30 · min(1, ln(1 + amount_minor / 100_000) / ln(1 + 25_000_000 / 100_000))`
(₹1,000 → ~7.7 · ₹4,999 → ~13.6 · ₹25,000 → ~20.4 · ₹75,000 → ~23.8 · ₹2,50,000+ → 30)

**reversibility_component (0–25)** — how fixable is this failure class:
| Diagnosis class | Points |
|---|---|
| NETWORK_INFRA | 25 |
| BANK_DOWNTIME | 22 |
| INSUFFICIENT_FUNDS | 20 |
| CUSTOMER_AUTH_REQUIRED | 16 |
| DUPLICATE_SELF_HEALED | 25 (moot — closes immediately) |
| INSTRUMENT_INVALID | 6 |
| UNKNOWN | 10 |

**customer_value (0–20)**: `10·min(1, lifetime_value_minor / 500_000_00) + 6·min(1, tenure_days/365) + 4·(prior_recoveries_90d > 0)` — proven payers are worth chasing.

**retry_history (0–15)**: paradoxically, *some* failure history with eventual recovery scores highest:
`attempt 0 → 15 · attempt 1 → 12 · attempt 2 → 8 · attempt ≥3 → 0` (budget gone).

**time_sensitivity (0–10)**: decays with age since failure: `10 · max(0, 1 − age_hours/48)` — fresh failures are recoverable; stale ones rot.

## 3. Bands, priority, SLA

| Band | Range | Priority queue | SLA to first action |
|---|---|---|---|
| CRITICAL | ≥75 | P0, worker preempts | 5 min |
| HIGH | 55–74 | P1 | 15 min |
| MEDIUM | 35–54 | P2 | 60 min |
| LOW | <35 | P3 | 24 h |

Tie-break: amount desc, then age asc. The score is computed once at DETECTED→ANALYZING and recomputed after each new observation (new attempt result, downtime change).

## 4. Confidence (separate from score)

Score ≠ confidence. Confidence attaches to the *diagnosis*:

| Evidence available | Base confidence |
|---|---|
| Structured `error_reason` mapped deterministically (e.g., `insufficient_funds`) | 0.90 |
| `error_code` only (e.g., GATEWAY_ERROR) | 0.70 |
| Description text needs interpretation (LLM judgment) | 0.60 |
| Conflicting signals / unknown | 0.40 |

LLM may adjust ±0.10 with stated evidence; final confidence = clamp(base + adjustment). Below 0.60 → P06 forces escalation. This keeps confidence honest: anchored to evidence strength, not model vibes.

## 5. Action recommendation hook

The engine does NOT choose strategies (that's agent + policy). It emits the priority context the agent consumes: `{risk_score, band, components breakdown}` — included in the case snapshot and shown in the UI so evaluators can verify the arithmetic.
