# RECOVERY_STRATEGIES.md — Bounded strategy catalog & decision matrix

## 1. Strategy catalog

| ID | Name | When applicable | Forbidden when | Expected outcome | Risk | Max attempts | Fallback |
|---|---|---|---|---|---|---|---|
| S1 | IMMEDIATE_RETRY | NETWORK_INFRA; BANK_DOWNTIME resolved; first attempt; token/mandate present | INSTRUMENT_INVALID; no token; cooldown active; downtime active (P09) | ~70–80% capture on transient faults | Low — same instrument, immediate | 1 per cooldown window | S2 |
| S2 | DELAYED_RETRY | INSUFFICIENT_FUNDS (salary-cycle timing); attempt ≥2 | TTL near expiry; no token | ~50–65% capture | Low | within ≤3 total retries | S3 |
| S3 | NOTIFY_WITH_LINK | CUSTOMER_AUTH_REQUIRED; INSTRUMENT_INVALID (update method); no saved token; post-retry nudge | contact cap hit (P08); amount needs approval first (P05) | ~30–45% link conversion | Low — customer-directed, no charge attempt | 3 messages / 7 days | S5 |
| S4 | ALT_PAYMENT_FLOW | card failed but UPI likely viable (method switch in link params) | repeated alt-flow failures; unknown diagnosis | modest uplift vs S3 | Low | 1 switch per case | S3 |
| S5 | HUMAN_ESCALATION | retry budget exhausted; amount ≥ ceiling; confidence < floor; UNKNOWN diagnosis; executor error; double policy block | never forbidden | human decides approve/reject | None (safest state) | 1 open escalation per case | S6 if rejected/expired |
| S6 | STOP_RECOVERY | ground truth unrecoverable classes (INSTRUMENT_INVALID after notify); TTL expiry; merchant cancel | — | case closed honestly UNRECOVERED | None | terminal | — |

## 2. Decision matrix (diagnosis × situation → default strategy)

Policy may still override; matrix is the deterministic fallback table AND the prior the LLM is prompted with.

| Diagnosis ↓ / Situation → | attempt 0, has token | attempt 0, no token | attempts 1–2 | high-value | low confidence | downtime active |
|---|---|---|---|---|---|---|
| INSUFFICIENT_FUNDS | S2 (+4h) | S3 | S2→S3 | S5 gate first | S5 | WAIT(P09) |
| NETWORK_INFRA | S1 now | S3 | S2 | S5 gate first | S5 | WAIT→S1 on resolve |
| BANK_DOWNTIME | WAIT until resolved | WAIT | WAIT | WAIT+gate | WAIT | — |
| CUSTOMER_AUTH_REQUIRED | S3 | S3 | S3 | gate+S3 | S5 | S3 ok |
| INSTRUMENT_INVALID | S3(update) | S3(update) | S6 after 1 notify | gate+S3 | S5 | S3 ok |
| DUPLICATE_SELF_HEALED | P02 stop | P02 stop | P02 stop | P02 stop | P02 stop | P02 stop |
| UNKNOWN | S5 | S5 | S5 | S5 | S5 | S5 |

## 3. Sequencing rules

- A case walks at most one path down the ladder: `S1/S2 (≤3 retries w/ cooldowns) → S3 (≤3 msgs) → S5 → S6`, always subject to TTL 72h.
- Cooldown schedule for retries: 30m → 2h → 8h (clamped by P13, accelerated to instant-completion in simulated-clock batch mode).
- Every strategy execution consumes exactly one action record with its own attempt_no — the audit shows the full ladder.

## 4. Why bounded catalogs beat free-form planning

The LLM chooses FROM this menu; it cannot invent strategies ("offer a discount coupon" is not an action we permit). This keeps every possible outcome auditable, testable, and policy-checkable — and makes the fallback table trivially correct when the LLM is unavailable.
