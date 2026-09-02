# DIFFERENTIATION.md — Standing out from the field

## What 80% of submissions will look like

Chat UI over payment data: "paste a failed payment → GPT explains why it failed → suggests an action." No execution, no verification, no measurement, fabricated demo numbers, prompt-only guardrails ("You are a careful assistant…").

## What the next 15% add

A working retry/notify action, maybe webhooks, a metrics page — but without idempotency rigor, policy traces, or honest real-vs-simulated boundaries.

## Our differentiators (in judge-value order)

1. **The gate.** A visible, rule-by-rule policy engine between agent and money. Demo 2 shows the AI being *refused*. Nobody demos their safety layer; we make it the star.
2. **Verified rupees, live.** Real Razorpay test checkout → real `payment.captured` webhook → dashboard counter ticks. Recovery is observed, not claimed.
3. **Zero-violation proof.** Evaluation harness with hard assertions (`violations==0`, `duplicates==0`) that turns red on failure — plus baselines quantifying the agent's marginal ₹ over naive retry-all.
4. **Honesty as engineering.** SIMULATED badges, integration capability matrix, documented test-mode limits. Evaluators trust what they can audit.
5. **Failure-first design.** Kill-the-LLM and duplicate-webhook demos on demand; degradation ladder documented before code was written.

## The "wow moment" candidates

- Primary: paying a REAL recovery link during the demo and watching the verified counter move within seconds.
- Secondary: replaying a webhook 3× and showing the idempotency ledger eat the duplicates.
- Tertiary: flipping the API key to invalid mid-run and watching FALLBACK decisions keep the system safe.

## Scripted vs improvised

3-minute cut: problem (30s) → Demo 1 live recovery (60s) → policy-block moment (30s) → evaluation report with zeros (45s) → close (15s).
5-minute cut adds high-value human gate + duplicate-webhook attack + LLM-kill resilience.

## Memorable framing lines

- "The LLM is the diagnostician, not the surgeon."
- "Every rupee it claims, Razorpay confirms."
- "We didn't build a chatbot that talks about payments. We built infrastructure that recovers them — and can prove it."
