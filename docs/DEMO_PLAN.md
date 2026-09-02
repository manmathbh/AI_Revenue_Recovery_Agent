# DEMO_PLAN.md — The 5-minute story

Narrative arc: *"Money fails silently every day. Recoup finds it, explains it, recovers it safely — and proves it with numbers."*

## Setup (before judges arrive)

`docker compose up` + `make seed && make batch SEED=42` pre-run so Overview shows a completed evaluation. Terminal with logs visible on second screen. Razorpay dashboard (test mode) open in a tab for the live-link moment.

## Demo 1 — Live recovery loop (90s) ★ wow moment

1. Create a real failed payment via test checkout (or send stored webhook).
2. Case appears DETECTED → watch it flow ANALYZING→DIAGNOSED.
3. Open Case Detail: diagnosis card (INSUFFICIENT_FUNDS, conf 0.86), rationale, policy checklist all green.
4. Action = REAL payment link → click it → pay ₹499 with test UPI/card in Razorpay checkout.
5. Webhook lands → status flips RECOVERED → Overview counter ticks up ₹499 live.
   *Line: "That recovery was verified by Razorpay itself — not claimed by the AI."*

## Demo 2 — Guardrails say no (45s)

Load S05 repeated-failure case: agent proposes retry #3 → policy P03 MAX_RETRIES blocks → fallback escalates → Escalation panel shows reason → approve with note → case proceeds gated.
*Line: "The agent asked, the policy engine refused, a human decided. In that order."*

## Demo 3 — High-value human gate (30s)

₹75,000 failure → P05 AMOUNT_CEILING → AWAITING_APPROVAL instantly regardless of agent confidence. Show the policy trace naming the rule.

## Demo 4 — Duplicate webhook attack (30s)

Replay identical `payment.failed` ×3 (`scripts/replay_webhook.py`). Timeline shows one case, two DUPLICATE events ignored, zero extra actions. Then show `duplicate_actions: 0` in metrics.

## Demo 5 — Batch proof (60s)

Run fresh batch seed=42 live (~2 min compressed: show progress bar, then open completed report): recovered ₹, rates, **policy violations 0 / duplicate actions 0** assertions green, baseline comparison chart (agent vs naive vs do-nothing).

## Q&A ammunition

- "What if LLM dies?" → flip `LLM_API_KEY=invalid`, re-run one case → FALLBACK origin badge, case still completes.
- "Is the data real?" → integration honesty table (RAZORPAY_INTEGRATION §1); SIMULATED badges; real webhook path demonstrated in Demo 1.
- "Show me the audit" → `/audit/RC-000042` hash chain valid.

## Timing budget

| Segment | Time |
|---|---|
| Problem framing | 0:00–0:30 |
| Demo 1 | 0:30–2:00 |
| Demos 2–4 | 2:00–3:45 |
| Demo 5 report | 3:45–4:45 |
| Close (architecture one-liner) | 4:45–5:00 |

Fallback if live internet fails: screen recording of Demo 1 + synthetic-path demos run locally (no external calls needed).
