# SCORECARD.md — Self-scoring framework (100 pts)

Rubric weights tuned to the published evaluation bar.

| Dimension | Weight | Our design target | Where it's earned |
|---|---|---|---|
| Problem relevance | 10 | 9 | Exact track loop; failed-payment focus |
| Technical depth | 15 | 13 | FSM, idempotency×5, ports/adapters, worker leases |
| AI/agent quality | 15 | 12 | Bounded tool-calling, fallback ladder, hallucination probes, accuracy vs ground truth |
| Razorpay integration | 12 | 11 | Real webhooks+links+downtime signals; honest limits register |
| Reliability | 12 | 11 | Chaos drills, circuit breaker, crash-consistency |
| Safety / guardrails | 12 | 12 | 14-rule engine, human gates, stopping rules, zero-violation asserts |
| Measurability | 10 | 10 | Seeded dataset, baselines, hard-asserted report |
| UX / dashboard | 6 | 5 | Decision/policy cards, live counter; not pixel-perfect |
| Demo quality | 5 | 5 | Rehearsed 3/5-min scripts with fallbacks |
| Innovation | 3 | 2 | Downtime-aware suppression, honesty-as-feature; core pattern is engineering excellence more than novelty |
| **Projected total** | **100** | **~90** | |

## Risks to the score

| Risk | Impact | Mitigation |
|---|---|---|
| LLM flaky/latency during live demo | −4 | FakeLLM mode + recording fallback; temperature=0; cheap fast model |
| Webhook tunnel unreachable on venue wifi | −4 | Synthetic injection path runs identical code locally |
| Time crunch cuts Phase 12–13 | −5 | P0 scope is phases 1–10 only; drills/security are the first cut if needed but keep webhook HMAC + idempotency (non-negotiable) |
| Judges probe "is recovery real?" | −3 if fumbled | Integration matrix answer rehearsed; SIMULATED badges pre-empt it |

## Five highest-impact improvements (if time is found)

1. **Baseline comparison chart in Evaluation view** — turns "we recovered ₹X" into "we recovered ₹X vs naive ₹Y (+Z%)" — the single strongest judged sentence.
2. **Downtime-aware suppression demo** (REC-016) — uses a documented Razorpay signal almost nobody else will touch.
3. **Audit hash-chain viewer** — 30-minute build, outsized "this team thinks like auditors" effect.
4. **Policy-config editor** — judges tune a threshold and watch behavior change safely.
5. **Decision replay sandbox** — "what-if" interactivity that shows deep system understanding.
