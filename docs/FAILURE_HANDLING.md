# FAILURE_HANDLING.md — Failure is a first-class state

Every scenario: Detection → Response → Retry? → Fallback → Escalation → Audit.

| # | Scenario | Detection | Immediate response | Retry? | Fallback | Escalation | Audit |
|---|---|---|---|---|---|---|---|
| 1 | LLM unavailable (connection refused) | exception on call | mark provider unhealthy (circuit opens 60s) | yes ×2 backoff | deterministic strategy table (`origin=FALLBACK`) | no (silent degradation) | decision row origin=FALLBACK, reason |
| 2 | LLM timeout (>20s) | timeout | same as #1; case wall-clock 60s budget | ×1 | fallback table | if repeated across cases → alert banner in dashboard | latency + fallback recorded |
| 3 | LLM returns invalid JSON/tool args | pydantic validation error | tool-error fed back to model once | strike counter ≤2 | fallback after strikes | no | invalid_call events in reasoning_trace |
| 4 | Razorpay API timeout | httpx timeout | circuit breaker counts | ×2 jittered backoff | action stays PENDING; sweeper reconciles by idempotency key | breaker open >5min → ops escalation | attempt + breaker state logged |
| 5 | Razorpay 5xx / rate limit | status code | honor Retry-After | ×2 | park case VERIFYING/POLICY_CHECK with SLA timer | sustained → escalation EXECUTOR_ERROR | full request id + status |
| 6 | Webhook duplicated | unique event_id conflict | return 200 duplicate:true, zero side effects | n/a | n/a | n/a | original event linked, dup count incremented |
| 7 | Webhook out-of-order (failed→captured) | captured arrives while case active | verification closes case SELF_HEALED / RECOVERED | n/a | n/a | n/a | both events on timeline |
| 8 | Webhook delayed/lost | case stuck VERIFYING past window | polling reconciliation fetches payment status | poll ×6 exp | close per live status | none | reconciliation event |
| 9 | DB unavailable | connection error at any write | webhook path returns 202 only after signature check, work lost-safe (Razorpay retries); worker backs off | exponential | read-only mode for dashboard | ops alert | post-recovery gap note |
| 10 | Invalid payment state for action (e.g., already captured) | pre-action live re-check | abort executor BEFORE gateway call | no | P02 stop → close RECOVERED/SELF_HEALED | no | aborted_action reason=STATE_CHANGED |
| 11 | Duplicate retry race (two workers) | unique(case_id,type,attempt_no) violation | loser exits cleanly | no | winner proceeds | no | constraint hit logged |
| 12 | Agent hallucination (invented state/tool) | schema+enum validation; registry whitelist | reject call, feed error | strikes≤2 | fallback table | low conf auto-escalates anyway | trace retained |
| 13 | Policy rejection | verdict BLOCK | strategy fallback once; second block → BLOCKED terminal or escalation | no | S5/S6 | yes when appropriate | rule trace persisted |
| 14 | Partial execution (link created, notify failed) | outbox write fails after gateway success | action marked SUCCEEDED_WITH_CAVEAT; notify retried by outbox worker | yes ×3 | suppress with reason | none | both halves journaled |
| 15 | Verification failure (no capture ever) | verify window lapses | attempts exhausted → CLOSED_UNRECOVERED | no | final customer message suppressed by contact cap rules | optional digest to merchant | outcome + all evidence links |
| 16 | Case pipeline crash mid-state | worker crash-reclaim via SKIP LOCKED lease expiry | resume from last committed state | yes | FSM guarantees no partial transition | repeated crashes → FAILED | every transition pre-committed |

## Global rules

1. **No silent success**: an action without a terminal result row is a bug and alerts.
2. **No retry storms**: every retry path has its own bounded counter separate from business retries.
3. **Crash-consistency**: state transitions commit before side effects; side effects carry idempotency keys so replays converge.
4. **Degradation is visible**: dashboard header shows LLM/Razorpay/DB health chips sourced from the same health checks.
