# GUARDRAILS.md — Policy / guardrail engine

## 1. Principle

> **The LLM proposes. The policy engine disposes.**

The policy engine is a pure, deterministic, ordered rule evaluator. No network calls, no LLM, no clocks read inline (time injected). Input: a `PolicyContext` (case + payment + customer aggregates + proposed action + config). Output: one verdict with machine-checkable reasons.

```python
class Verdict(str, Enum):
    ALLOW    = "ALLOW"      # execute as proposed
    BLOCK    = "BLOCK"      # forbidden; case follows fallback path
    ESCALATE = "ESCALATE"   # permitted only via human approval
    WAIT     = "WAIT"       # re-schedule (cooldown/downtime)

@dataclass(frozen=True)
class PolicyResult:
    verdict: Verdict
    triggered_rules: list[RuleHit]   # [{rule_id, passed, reason}]
    evaluated_at: datetime
```

Rules run in fixed order; **any hard-fail short-circuits**; every rule's pass/fail is recorded even after short-circuit of later rules is skipped — the audit shows exactly which rule decided.

## 2. Rule catalog

| ID | Rule | Logic | Why it exists |
|---|---|---|---|
| P01 | STATE_ELIGIBLE | `case.status ∈ {DIAGNOSED, PLANNED, AWAITING_APPROVAL→APPROVED}` and `payment.status == FAILED` | Never act on non-failed money (prevents acting on captured/authorized payments) |
| P02 | ALREADY_RECOVERED | live check: payment not captured AND no other captured payment for order | Stopping rule #1 — self-healed cases must stop instantly |
| P03 | MAX_RETRIES | `retry_count < 3` for retry-type actions | Bounded attempts; prevents harassment and gateway abuse |
| P04 | COOLDOWN | `now ≥ last_attempt_at + cooldown(attempt_n)` (30m × 2^n, clamped 30m–24h) | Spacing retries raises success odds; mimics mandate-retry best practice |
| P05 | AMOUNT_CEILING_AUTO | `amount_minor ≤ 25_000_00` for autonomous execution | High-value money requires human sign-off |
| P06 | CONFIDENCE_FLOOR | `min(diagnosis_confidence, strategy_confidence) ≥ 0.60` | Low-confidence agent judgment must not touch money |
| P07 | DUPLICATE_ACTION | no existing action row `(case_id, action_type, attempt_no)` (DB unique constraint backstop) | Idempotency at the gate, not just the DB |
| P08 | CONTACT_CAP | outbound customer messages ≤ 3 per customer per rolling 7 days | Compliance/anti-spam |
| P09 | DOWNTIME_HOLD | if `check_downtime` active for method/bank → retry actions become WAIT until resolved | Don't punish customers for bank outages; don't burn attempts during downtime |
| P10 | DIAGNOSIS_ACTION_COMPAT | strategy allowed for diagnosis class (matrix in RECOVERY_STRATEGIES §3) | e.g., never auto-retry EXPIRED_CARD |
| P11 | TTL | `case.age < 72h` else EXPIRE | Every workflow terminates |
| P12 | SIMULATION_BUDGET | global cap on simulated charge attempts per batch run (e.g., 200) | Cost/abuse bound on executor |
| P13 | PARAM_SANITY | delay clamped to [15m, 72h]; link_amount == original amount; channel ∈ {sms,email} | LLM cannot smuggle weird parameters |
| P14 | AUDIT_WRITE_SUCCEEDS | decision+policy rows committed before executor invoked | No unaudited side effects, ever |

Escalation triggers (route to human): P03 exhausted, P05 breach, P06 breach, two BLOCKs on same case, UNKNOWN diagnosis with risk ≥ HIGH.

## 3. Worked examples

```
Case RC-007: ₹4,999 failed, INSUFFICIENT_FUNDS, attempt 1, conf 0.86
  → P01✓ P02✓ P03✓(1<3) P04✓ P05✓(4999≤25000) P06✓ ... → ALLOW (execute S2)

Case RC-019: ₹75,000 failed, conf 0.9
  → P05 fails → ESCALATE("amount above auto-approval ceiling") → AWAITING_APPROVAL

Case RC-031: attempt 3 already made, agent proposes S1
  → P03 fails → BLOCK → fallback table → S5 escalation

Case RC-044: netbanking downtime active, agent proposes immediate retry
  → P09 → WAIT(until downtime.resolved) — attempt budget NOT consumed
```

## 4. Configuration

All thresholds in `policy_config` table (per-merchant, seeded defaults shown above) so judges can see/tune them; engine reads config snapshot per evaluation; changes are themselves audited.

## 5. Testing contract

Pure functions ⇒ exhaustive unit tests: every rule × {pass, fail, boundary} × interaction matrix (~120 cases), plus property test: "no sequence of DecisionRecords can produce an executor call without an ALLOW/ESCALATE-approved verdict" (enforced again by executor-side assertion).
