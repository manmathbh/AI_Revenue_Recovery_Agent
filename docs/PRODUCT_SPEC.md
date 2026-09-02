# PRODUCT_SPEC.md — Recoup

> **Recoup** — *the bounded AI revenue recovery agent for Razorpay merchants.*
> "Recoup": to regain what was lost. The name promises exactly what we measure.

## Target user

Primary persona: **"Priya", Head of Revenue Ops** at an Indian mid-market online business (D2C brand or subscription SaaS) doing ₹50L–5Cr/month through Razorpay.

Secondary personas evaluated by judges: finance/support leads who handle failed-payment follow-ups today by hand.

## Problem

Every month Priya's store loses lakhs to failed payments that were actually recoverable. Her team has no way to know which failures matter, why they happened, or what safe action to take — so they either ignore them or spam customers with generic emails.

## Input

| Source | Data | Mode |
|---|---|---|
| Razorpay webhooks | `payment.failed` (with `error_code/source/step/reason`), `payment.captured`, `payment.downtime.*` | Real, test mode, HMAC-verified |
| Razorpay REST | payment fetch, order payments list, customer, payment link create/fetch | Real, test mode |
| Merchant config | policy thresholds (max retries, approval limit, cooldowns) | Seeded defaults, editable in UI (stretch) |
| Synthetic batch | 120 ground-truthed recovery opportunities | Generated, seeded |

## Processing (the loop)

```
Detect      webhook ingestion → dedupe → create RecoveryCase (DETECTED)
Understand  enrich: customer history, prior attempts, downtime window, order context
Diagnose    deterministic error-code mapping + LLM reasoning → diagnosis class + confidence
Decide      risk score → priority; agent proposes ONE strategy from bounded catalog
Validate    policy engine evaluates hard rules → ALLOW / BLOCK / ESCALATE / WAIT
Execute     single idempotent action executor call (retry | link | notify | escalate)
Verify      await webhook / poll payment status; detect self-heals; confirm captured ₹
Measure     update case + run metrics from DB
Audit       append-only event log for every transition, decision, and gate result
Escalate    stopping rules route leftovers to a human approval queue
```

## Output (what the merchant sees)

Dashboard with four views:

1. **Overview** — Revenue at Risk, Recovered (₹, live-updating), Recovery Rate, Active Cases, Escalations Pending.
2. **Cases** — sortable table: customer (masked), amount, diagnosis, risk band, recommended action, status.
3. **Case Detail** — the full story: timeline, agent decision card (diagnosis, chosen strategy, confidence, rationale summary), policy verdicts with rule IDs, executed actions with results, audit trail.
4. **Evaluation** — batch report: recovered ₹, rates, violations=0, duplicates=0, accuracy vs ground truth.

## Actions the agent can take (complete list)

| Tool | Side effects | Gated by policy? |
|---|---|---|
| `get_case_context` | none (read) | n/a |
| `get_customer_history` | none (read, masked PII) | n/a |
| `get_payment_status` | none (read) | n/a |
| `check_downtime` | none (read) | n/a |
| `propose_strategy` | none (writes decision record only) | recorded |
| `execute_retry_charge` | money attempt (token charge) | YES — full gate |
| `send_recovery_link` | creates real test-mode payment link + outbox message | YES — full gate |
| `create_escalation` | human task created | YES — lighter gate |

The LLM can **propose** any of these; only the policy engine can **permit** side-effectful ones.

## Human intervention points

The agent stops and asks a human when ANY of:

- Amount ≥ ₹25,000 (approval threshold)
- Agent confidence < 0.60
- Retry budget exhausted (≥3 attempts) without recovery
- Diagnosis = UNKNOWN with HIGH/CRITICAL risk
- Policy BLOCKS twice on the same case
- Any internal error during execution (case → FAILED → escalation)

Approvals happen in the dashboard (approve/reject with reason); approving re-enters the pipeline at APPROVED.

## Definition of success

1. **Money**: verified recovered ₹ > 0 across the batch; recovery rate reported honestly against ground truth.
2. **Safety**: zero policy violations, zero duplicate financial actions, zero unapproved high-value executions — asserted by the evaluation harness.
3. **Explainability**: any case reconstructable end-to-end from its audit trail alone.
4. **Resilience**: kill the LLM mid-run → system still completes cases via deterministic fallback; kill Razorpay connectivity → cases park in VERIFYING/FAILED with clean audit, no corruption.
