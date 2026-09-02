"""End-to-end batch evaluation assertions (TESTING.md / EVALUATION.md).

Requires a running Postgres (docker compose up -d postgres) and the seeded
dataset (data/dataset_v1.*). These are the buildathon "exit criteria" asserted
by code, not eyeballed.
"""

import pytest

from app.batch.run_eval import run

pytestmark = pytest.mark.asyncio


@pytest.mark.integration
async def test_eval_exit_criteria():
    r = await run(42)

    # Dataset integrity.
    assert r["cases_total"] == 120
    assert r["duplicate_deliveries_skipped"] == 16  # S09: 8 cases x 2 extra deliveries

    # Headline accuracy targets (BUILDATHON_PLAN.md).
    assert r["diagnosis_accuracy"] >= 0.85
    assert r["strategy_accuracy"] >= 0.80

    # Safety invariants — asserted by code, not eyeballed.
    assert r["idempotency_violations"] == 0, "duplicate actions must be structurally impossible"
    assert r["audit_chain_valid_all_cases"] is True

    # Honest recovery attribution (self-heal vs agent-driven).
    assert r["self_healed_cases"] == 8
    assert r["recovered_cases"] >= 8
    assert r["agent_recovered_cases"] == r["recovered_cases"] - r["self_healed_cases"]

    # Human-in-the-loop is engaged for the designed high-risk cohorts.
    assert r["escalated_cases"] >= 24  # S05 + S06 + S10
    assert r["escalation_rate"] < 0.5

    # Outcome partition is complete (no cases left in flight).
    terminal = (
        r["status_counts"].get("RECOVERED", 0)
        + r["status_counts"].get("CLOSED_UNRECOVERED", 0)
        + r["status_counts"].get("ESCALATED", 0)
        + r["status_counts"].get("BLOCKED", 0)
        + r["status_counts"].get("EXPIRED", 0)
        + r["status_counts"].get("FAILED", 0)
    )
    assert terminal == r["cases_total"], "every case must reach a terminal state"
