# TECH_STACK.md — Technology decision

## Options considered

| Criterion | A. Go + PG + React | B. Node/TS + PG + Next.js | C. Python + FastAPI + PG + Next.js |
|---|---|---|---|
| Build speed (hackathon) | 3 (verbose, slower iteration) | 4 (one language full-stack) | **5** (fastest backend iteration) |
| Reliability (type safety, concurrency) | **5** | 4 | 3.5 (mitigated by pydantic + type hints) |
| Razorpay API integration | 4 (fine, manual DTOs) | 4 (official-ish SDKs community) | **5** (`razorpay` official Python SDK + httpx) |
| Agent/LLM ecosystem | 2 (immature tool-calling ecosystem) | 4 (Vercel AI SDK good) | **5** (OpenAI SDK tool calling, pydantic→JSON Schema native) |
| Testing | 4 | 4 | **5** (pytest + respx + factories fastest to write) |
| Maintainability (for judges reading code) | 4 | 4 | **4** (clear structure, typed models) |
| Fits existing backend/systems skills | high if Go background | high if TS background | **high — general backend skills transfer immediately; least framework fighting under deadline** |
| Explaining architecture in evaluation | 4 | 4 | **5** (explicit ports/adapters, policy engine reads like pseudocode) |

## Decision: Option C — Python 3.12 + FastAPI + PostgreSQL 16 + Next.js 14

Chosen for **time-to-working-system** and **agent ecosystem fit**, not popularity:

- **Pydantic v2 is the killer feature**: one model class = runtime validation + JSON Schema for LLM tool definitions + OpenAPI docs. The agent's tool schemas and the policy engine's typed inputs come from the same source of truth.
- **FastAPI**: async webhook ingestion, dependency-injected DB sessions, automatic OpenAPI for the dashboard team.
- **SQLAlchemy 2.0 + Alembic**: explicit schema migrations make the data model a reviewable artifact.
- **Next.js + Tailwind**: polished demo dashboard quickly; talks only to our REST API.

### What we deliberately do NOT add

| Tech | Verdict | Why |
|---|---|---|
| Redis | ❌ MVP | DB-backed job claim (`FOR UPDATE SKIP LOCKED`) suffices at 120-case scale; add later for real throughput |
| Celery/RQ workers | ❌ MVP | One async worker loop inside the FastAPI process (APScheduler-style); fewer moving parts to demo |
| Vector DB / RAG | ❌ | No unstructured knowledge corpus exists in this problem |
| Docker | ✅ compose only | Postgres + app + dashboard orchestration for one-command demo; no k8s |
| Message queue | ❌ | Webhook → DB transaction → worker poll is simpler and fully auditable |

### Locked stack

```
Backend    Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.0, Alembic,
           httpx (Razorpay client), structlog (JSON logs), pytest
LLM        OpenAI-compatible Chat Completions with TOOL CALLING.
           Provider-agnostic via env: OPENAI_API_KEY | GROQ | any compatible endpoint.
           Cheap fast model class (e.g., gpt-4o-mini tier) is sufficient.
Database   PostgreSQL 16 (docker compose)
Frontend   Next.js 14 App Router, TypeScript, Tailwind, TanStack Query
Tooling    ruff, mypy, pre-commit, GitHub Actions (lint+test)
```

### When we would choose differently

- Team already deep in Go and >1 week available → Option A (superior long-run reliability).
- Solo dev strongest in TS wanting literally one language → Option B.
- Neither applies: C wins on deadline risk, which is the binding constraint in a buildathon.
