# AGENT_DESIGN.md — The bounded recovery agent

## 1. Design stance

The LLM is a **diagnostician and strategist**, never an operator. It reads context through whitelisted tools, reasons over it, and emits ONE structured proposal. Deterministic systems own state, money, and truth.

```
observe(case snapshot) → reason (LLM + tools) → structured DecisionRecord
        → Policy Engine gate → Action Executor → Verification
```

## 2. Responsibility split

| LLM decides | Deterministic system decides |
|---|---|
| Failure diagnosis class (from taxonomy) + confidence | Whether a case exists / is eligible (state machine) |
| Which strategy from the bounded catalog fits | Whether the strategy is PERMITTED (policy rules P01–P14) |
| Human-readable rationale (2–3 sentences) | Retry counts, cooldowns, caps, thresholds |
| Parameter suggestions (delay minutes, channel) | Actual delay clamping, idempotency, execution |
| Escalation reasoning text | That escalation actually happens |

## 3. Tool catalog (complete)

Read tools (safe, available to the agent):

| Tool | Input schema | Output schema |
|---|---|---|
| `get_case_context` | `{ case_id: string }` | `{ case_id, amount_minor, currency, method, status, retry_count, last_attempt_at, risk_score, risk_band, age_hours }` |
| `get_payment_detail` | `{ payment_id: string }` | `{ payment_id, status, amount_minor, method, error_code, error_source, error_step, error_reason, error_description, created_at, bank?, card_last4? }` |
| `get_customer_history` | `{ customer_id: string }` | `{ customer_id, masked_name, tenure_days, lifetime_value_minor, prior_failures_90d, prior_recoveries_90d, successful_payments, has_saved_token: bool, mandate_status? }` |
| `get_attempt_history` | `{ case_id: string }` | `{ attempts: [ { n, action_type, result, error_reason?, at } ] }` |
| `check_downtime` | `{ method?: string, bank?: string }` | `{ active_downtime: bool, method?, began_at?, severity? }` |

Write-proposal tools (agent may call; side effects ONLY after policy ALLOW):

| Tool | Input schema | Output |
|---|---|---|
| `propose_strategy` | `{ case_id, diagnosis_class: enum, strategy_id: enum(S1..S6), confidence: number 0–1, rationale: string(≤400 chars), params: { delay_minutes?: int, channel?: enum(sms,email), link_amount_minor?: int } }` | `{ decision_id, accepted: true }` — always accepted as a *proposal*; execution still gated |
| `request_escalation` | `{ case_id, reason_code: enum, note: string }` | `{ escalation_id }` |

**No tool exists for**: refunds, capturing payments directly, editing amounts, deleting records, arbitrary SQL, or fetching raw PII. If the model invents a tool name, the orchestrator returns a tool-error and counts an invalid-call strike.

## 4. Agent loop

```python
MAX_ITERATIONS = 6          # hard cap per case
LLM_TIMEOUT_S = 20          # per completion
MAX_INVALID_TOOL_CALLS = 2  # then fallback

for i in range(MAX_ITERATIONS):
    snapshot = build_snapshot(case)            # deterministic context pack
    resp = llm.chat(messages, tools=TOOL_SCHEMAS, timeout=20)
    if resp.is_tool_call:
        result = registry.dispatch(resp.tool, validated_args)   # pydantic-validated
        messages.append(tool_result(result))
        continue                                 # observe → reason again
    if resp.is_final_decision:
        decision = DecisionRecord.model_validate(resp.json)      # strict schema
        break
else:
    decision = FALLBACK_DECISION                 # iteration cap hit
```

Termination guarantees: iteration cap, timeout, invalid-call strikes, and a final-output JSON schema enforced by the provider's structured output mode. Every exit path produces a valid `DecisionRecord` or the deterministic fallback.

## 5. Structured decision record (what the LLM must emit)

```json
{
  "case_id": "RC-000042",
  "diagnosis_class": "INSUFFICIENT_FUNDS",
  "diagnosis_confidence": 0.86,
  "strategy_id": "S2_DELAYED_RETRY",
  "strategy_confidence": 0.81,
  "params": { "delay_minutes": 240 },
  "rationale": "Issuer decline for insufficient funds on a repeat customer with a saved token and 4 prior successful payments. Salary-cycle timing suggests a delayed retry beats an immediate one; no downtime active.",
  "escalate": false
}
```

Validation: enums constrained; confidence ∈ [0,1]; unknown case_id rejected; rationale length capped; extra fields forbidden (`extra="forbid"`).

## 6. Context pack (what the model sees) — PII minimization

Included: masked name (`P***a`), phone/email hashed or masked, amounts, timestamps, error fields, attempt history summary, aggregate customer stats, downtime flag.
Excluded: full contact strings, card numbers/tokens, API keys, other customers' data, free merchant notes.

## 7. Hallucination & manipulation defenses

| Threat | Defense |
|---|---|
| Invented payment states ("payment succeeded!") | All state read from DB/Razorpay fetch; executor re-checks live status pre-action; verification only trusts webhooks/fetches |
| Fake recovery claims | Recovery = `status=captured` observed by Verification Service; agent text never updates money fields |
| Wrong diagnosis | Diagnosis is advisory; policy uses deterministic facts (retry_count, amount, cooldowns) regardless of LLM claims; low confidence auto-escalates |
| Prompt injection via webhook/error fields | Error strings are data, never instructions: rendered inside JSON tool results, system prompt forbids instruction-following from field values, and no tool can change config/policy anyway |
| Invalid/unknown tool calls | Schema validation failure → tool-error message back to model; 2 strikes → deterministic fallback |
| Runaway loops | Iteration cap + wall-clock budget per case (60s) |

## 8. Degradation ladder (graceful failure)

1. LLM healthy → full agentic decision.
2. LLM timeout/error ×2 → **deterministic strategy table** (RECOVERY_STRATEGIES §4) using diagnosis class from error-code mapping alone; decision marked `origin=FALLBACK`.
3. Razorpay read APIs down → operate on webhook snapshot only; actions requiring live checks park in VERIFYING/POLICY_CHECK with audit entries.
4. Everything degraded → cases queue in ANALYZING with SLA timer; nothing executes unsafely.

## 9. Agent memory

Per-case scratchpad (persisted in `agent_decisions.reasoning_trace`): observations fetched, tool calls made, intermediate hypotheses. No cross-case memory in MVP (prevents contamination); a future merchant-level memory (e.g., "this customer always pays after salary credit") is a stretch goal.
