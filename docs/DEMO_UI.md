# DEMO_UI.md — Dashboard design

Next.js 14 + Tailwind + TanStack Query. Polling (2s on active views) instead of websockets — simpler, demo-reliable. Design language: clean fintech dark-mode, monospace numerals for money, color semantics: green=recovered, amber=escalation/wait, red=blocked/failed, blue=in-flight, gray=simulated badge.

## Views

### 1. Overview (`/`)
KPI cards: **Revenue at Risk** · **Revenue Recovered** (live counter — the hero number) · Recovery Rate · Active Cases · Escalations Pending.
Secondary strip: self-healed count, blocked count, policy violations (must read 0), duplicate actions (0), LLM/Razorpay health chips.
Mini chart: recovered ₹ over batch progress (sparkline).

### 2. Cases (`/cases`)
Table: Case Ref · Customer (masked) · Amount · Method · Diagnosis chip · Risk band pill (CRITICAL red→LOW gray) · Strategy · Status stepper · Age vs SLA.
Filters: status, risk band, outcome. Row click → detail. Bulk action: "Run batch" button (posts `/batch/runs`) with live progress bar.

### 3. Case Detail (`/cases/[ref]`) — the money view
Layout:
- Header: amount, status stepper (DETECTED→…→RECOVERED), execution-mode badges (REAL/SIMULATED).
- **Agent Decision card**: diagnosis + confidence bar, chosen strategy, rationale quote, origin (LLM/FALLBACK), decision id, iterations used.
- **Policy card**: verdict + rule checklist P01–P14 with ✓/✗ and reasons (the safety theater that wins judges).
- **Actions list**: type, attempt no, mode badge, gateway ref link (real payment link URL opens Razorpay test checkout!), result.
- **Timeline**: merged audit events (webhooks, transitions, decisions, policy, actions, escalations) with actor icons and timestamps.
- Escalation panel (when present): reason, note, Approve/Reject buttons with required note.

### 4. Evaluation (`/evaluation`)
Run selector → report table exactly as EVALUATION.md format; assertion badges (violations=0 ✓); baseline comparison bars (agent vs rules-only vs naive vs do-nothing); diagnosis accuracy by scenario breakdown.

### 5. Audit (`/audit/[ref]`)
Raw audit events JSON viewer + chain validity indicator (for the skeptical engineer-judge).

## Interaction details that matter in judging

- Live-updating recovered counter during batch run = visceral "money coming back".
- Clicking a REAL payment link opens actual Razorpay test checkout → pay with test instrument → dashboard flips to RECOVERED within seconds via real webhook. This is the wow moment.
- SIMULATED badges everywhere simulation exists — honesty as a UI feature.
- No chat window anywhere. The agent is infrastructure, not a chatbot.

## Non-goals for UI

Auth screens, multi-merchant nav, charts library bloat, mobile responsiveness beyond "not broken", animations beyond polling transitions.
