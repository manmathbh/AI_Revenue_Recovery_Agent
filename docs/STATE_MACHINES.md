# STATE_MACHINES.md — Explicit workflow states

## 1. RecoveryCase FSM (authoritative)

```
                       ┌────────────┐
   webhook(sanitized)──▶│  DETECTED  │
                       └─────┬──────┘
                             │ worker claims case
                       ┌─────▼─────────┐     enrichment/risk failure ×3
                       │  ANALYZING    │──────────────────────────┐
                       └─────┬─────────┘                          ▼
                             │ snapshot ready, agent invoked  ┌────────┐
                       ┌─────▼─────────┐                      │ FAILED │
                       │   DIAGNOSED   │  agent error/cap hit │        │
                       │ (decision ok) │─────────────────────▶└────────┘
                       └─────┬─────────┘
                             │ strategy selected
                       ┌─────▼─────────┐
                       │    PLANNED    │
                       └─────┬─────────┘
                             │ policy evaluation requested
                       ┌─────▼─────────┐
              ┌────────│  POLICY_CHECK │───────────────┐
              │        └─────┬─────────┘               │
     ALLOW/ESCALATE-approved │ BLOCK×1                 │ BLOCK×2 or ESCALATE
              │              │ (fallback strategy      ▼
              │              │  re-enters here)  ┌────────────────────┐
              │        ┌─────▼─────────┐         │ AWAITING_APPROVAL  │──approve──▶(POLICY_CHECK)
              │        │   APPROVED    │         └─────────┬──────────┘            │
              │        └─────┬─────────┘          reject/48h timeout                  │
              │              │ executor claimed                └──▶ ESCALATED ────────┤
              │        ┌─────▼─────────┐                                              │
              │        │   EXECUTING   │──executor hard error──▶ FAILED               │
              │        └─────┬─────────┘                                              │
              │              │ side effect accepted                                   │
              │        ┌─────▼─────────┐   captured webhook/fetch (ours or self-heal) │
              │        │   VERIFYING   │──────────────▶ RECOVERED ◀───────────────────┘(via approved action)
              │        └─────┬─────────┘                    │
              │   TTL 72h /  │  all attempts exhausted      │ metrics finalize
              │  escalation  │  & last verify missed        ▼
              └─────────────▶├──────────────────────▶ CLOSED_UNRECOVERED
                             ├──▶ EXPIRED (TTL)
                             ├──▶ CANCELLED (merchant/admin)
                             └──▶ BLOCKED (terminal policy refusal, nothing left to try)
```

## 2. Transition table

| From | To | Trigger | Actor |
|---|---|---|---|
| DETECTED | ANALYZING | worker claim | worker |
| ANALYZING | DIAGNOSED | valid DecisionRecord persisted | orchestrator |
| ANALYZING | FAILED | 3 consecutive pipeline errors | worker |
| DIAGNOSED | PLANNED | strategy set from decision/fallback | orchestrator |
| PLANNED | POLICY_CHECK | gate evaluation starts | orchestrator |
| POLICY_CHECK | APPROVED | verdict ALLOW (or approved escalation re-entry passes) | policy engine |
| POLICY_CHECK | AWAITING_APPROVAL | verdict ESCALATE | policy engine |
| POLICY_CHECK | PLANNED | verdict BLOCK → fallback strategy chosen (once) | orchestrator |
| POLICY_CHECK | BLOCKED | second BLOCK, no fallback remains | policy engine |
| AWAITING_APPROVAL | APPROVED | human approve (reason recorded) | human |
| AWAITING_APPROVAL | ESCALATED | reject or 48h timeout | human/scheduler |
| APPROVED | EXECUTING | executor claim + pre-action live checks pass | executor |
| EXECUTING | VERIFYING | gateway accepted request (or link created) | executor |
| EXECUTING | FAILED | hard executor error (audited, escalation raised) | executor |
| VERIFYING | RECOVERED | captured observed for this order | verification svc |
| VERIFYING | CLOSED_UNRECOVERED | attempts exhausted + verify window lapsed | scheduler |
| any non-terminal | EXPIRED | age > 72h | scheduler |
| any non-terminal | CANCELLED | admin action | human |
| VERIFYING | RECOVERED(SELF_HEALED) | captured observed with zero executed actions | verification svc |

Terminal states: `RECOVERED, CLOSED_UNRECOVERED, EXPIRED, CANCELLED, BLOCKED, FAILED*, ESCALATED**` (*FAILED re-drives to ESCALATED via alert; **ESCALATED terminal until an approval spawns a fresh gated sub-flow).

## 3. Invariants (enforced in code + tested)

1. Transitions only via `case_service.transition(case, to_state)` which validates against the table above inside the same DB transaction.
2. Terminal states are immutable.
3. Every transition writes an `audit_events` row (actor, reason, from→to).
4. Money fields (`recovered_amount_minor`) writable ONLY by Verification Service on observed capture.
5. A case has at most one open action of any type (unique index).

## 4. Secondary FSMs

**RecoveryAction**: `PENDING → GATED(ALLOW) → EXECUTING → SUCCEEDED | FAILED | SUPERSEDED` — superseded when a later attempt replaces a WAIT-scheduled one.

**Escalation**: `OPEN → APPROVED | REJECTED | EXPIRED` — APPROVED emits an APPROVED-transition back into the case flow.

**Payment mirror**: `created → authorized → captured | failed` mirroring Razorpay statuses; never edited by hand — only from verified webhooks/fetches.
