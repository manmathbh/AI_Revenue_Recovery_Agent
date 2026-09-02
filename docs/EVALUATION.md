# EVALUATION.md — Proving it works

## 1. Principle

Every number comes from SQL over actual execution records (`eval_runs`, `recovery_cases`, `recovery_actions`, `policy_decisions`). The report generator refuses to run if invariants fail; violations are surfaced, not hidden.

## 2. Metric definitions

| Metric | Formula | Target |
|---|---|---|
| Revenue at risk | Σ amount_minor of cases reaching DIAGNOSED+ | context |
| Recovered revenue | Σ recovered_amount_minor where outcome ∈ {RECOVERED} | maximize |
| Recovery rate | recovered_cases / eligible_cases | report honestly |
| Amount-recovery rate | recovered_revenue / at_risk_revenue | report honestly |
| Self-heal rate | SELF_HEALED / eligible | attribution honesty |
| Policy violation rate | actions executed without ALLOW/approved verdict OR any rule bypass | **0 (hard assert)** |
| Duplicate action rate | recovery_actions rows violating unique intent (attempted inserts beyond first per key) | **0 (hard assert)** |
| False action rate | actions on cases ground-truth `recoverable=false` or wrong-state | ≈0 |
| Escalation rate | ESCALATED / total | sane band 15–30% |
| Agent accuracy | match(expected_diagnosis, actual) and match(expected_strategy, actual) vs ground truth | ≥85% diagnosis |
| Fallback rate | decisions origin=FALLBACK / total | <20% (LLM health) |
| Mean time-to-recovery | avg(recovered_at − case_created_at) | report |
| Mean iterations / latency | agent loop stats | ≤6 / ≤60s |

## 3. Report format (generated, `reports/run_<ref>.md` + `.json`)

```
Total cases:              120
Revenue at risk:          ₹18,42,300
Recovered cases:          61
Recovered revenue:        ₹9,87,450
Recovery rate:            50.8%
Amount-recovery rate:     53.6%
Self-healed:               9   (₹1,31,200)
Escalated:                24
Blocked by policy:        17
Expired:                   6
Duplicate actions:          0      ← asserted
Policy violations:          0      ← asserted
Diagnosis accuracy:      89.2%
Strategy accuracy:       81.7%
Fallback rate:           12.5%
Mean time-to-recovery:   41m
```

(Illustrative shape only — real numbers emitted by `scripts/evaluate.py --run <ref>`.)

## 4. Hard assertions inside the evaluator

```python
assert policy_violations == 0, dump_violating_rows()
assert duplicate_actions == 0
assert every RECOVERED case has a captured payment observation (webhook or fetch)
assert every EXECUTED action has a policy_decisions row with verdict ALLOW
             or an APPROVED escalation
assert audit chain hashes validate for all cases
```

If any assertion fails, the run is marked INVALID and the dashboard shows it red. A red evaluation is itself evidence the safety story is real.

## 5. Baselines for comparison (same dataset)

| Baseline | Meaning |
|---|---|
| B0 Do-nothing | recovered = self-heals only |
| B1 Naive retry-all×3 | retry everything thrice blindly |
| B2 Rules-only (no LLM) | deterministic fallback table alone |

Running B0/B1/B2 alongside the full agent quantifies the LLM's marginal value — a judge-facing chart: *"agent recovers ₹X vs naive ₹Y (+Z%)"*. Cheap to implement since all three are just strategy sources into the same engine.

## 6. Reproducibility checklist

fixed seed · pinned model name+temperature=0 · config snapshot stored per run · containerized deps · single command: `make evaluate SEED=42`.
