# Recoup — AI Revenue Recovery Agent

The bounded AI revenue recovery agent for Razorpay merchants (Razorpay Buildathon, Track 03).

Recoup detects failed payments, diagnoses why they failed, executes policy-gated recovery
actions through Razorpay, and proves every rupee recovered with a zero-violation audit trail.

> **The LLM is the diagnostician, not the surgeon — and every rupee it claims, Razorpay confirms.**

Full design lives in `docs/` (the frozen spec of record). This README is the quickstart only.

## Quickstart

```bash
# 1. Install deps
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 2. Configure
cp .env.example .env   # set RAZORPAY_* test keys, leave LLM_API_KEY empty for fallback mode

# 3. Provision the database (docker compose up postgres, or a local PG 16)
docker compose up -d postgres
alembic upgrade head

# 4. Generate + load the frozen dataset, run a full batch
make seed && make batch

# 5. Produce the evaluation report
make evaluate

# 6. Run the API + worker
make dev           # API on :8000
make worker        # worker loop on :8001 (or `python -m app.worker`)
```

## Honest simulation boundary

| Capability | Mode |
|---|---|
| `payment.failed` / `payment.captured` webhooks (HMAC-SHA256 verified) | **REAL** (test mode) |
| Payment Links create / fetch | **REAL** (test mode) |
| Payment fetch / order payments | **REAL** |
| `payment.downtime.*` webhooks | **REAL** (P1) |
| Server-side token-charge retries | **SIMULATED** (labeled end-to-end) |
| SMS/email delivery | **OUTBOX** (SIMULATED_SENT) |

Every simulated action carries `execution_mode=SIMULATED` through the DB, API, and UI.

## Repository layout

```
app/            FastAPI app (api, domain, agent, executors, verification, integrations, db, obs)
scripts/        generate_dataset, load_dataset, evaluate, replay_webhook, demo_reset
data/           dataset_v1.jsonl + ground truth (committed, seed 42)
tests/          unit, integration, e2e, agent_eval
frontend/       Next.js dashboard
reports/        generated evaluation reports
```

## Commands

| Command | Purpose |
|---|---|
| `make test` | pytest suite (unit + integration) |
| `make lint` | ruff |
| `make typecheck` | mypy |
| `make seed` | generate + load the 120-case dataset |
| `make batch` | run a full recovery batch |
| `make evaluate` | emit the hard-asserted evaluation report |
| `make demo-reset` | reset to a clean demo state |
