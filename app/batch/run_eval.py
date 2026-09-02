"""Batch evaluation runner (TESTING.md e2e suite).

Replays data/dataset_v1.jsonl through the live stack (ingest -> pipeline),
then scores eval_case_results against the ground truth. Deterministic: same
seed -> same report (single-process, virtual clock anchored at dataset t0).

Usage: python -m app.batch.run_eval [--seed 42] [--keep-db]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, func, select

from app.db.enums import CaseStatus, ExecutionMode
from app.db.models import (
    AgentDecision,
    AuditEvent,
    Customer,
    Escalation,
    EvalCaseResult,
    EvalRun,
    Merchant,
    Notification,
    Payment,
    PolicyDecision,
    RecoveryAction,
    RecoveryCase,
    WebhookEvent,
)
from app.db.models import (
    Counter as RefCounter,
)
from app.db.session import session_scope
from app.executors.actions import ExecutorDeps
from app.integrations.simulated_gateway import SimulatedGatewayAdapter
from app.policy.config import PolicyConfig
from app.services import audit
from app.services.ingest import ingest_event
from app.services.pipeline import VirtualClock, advance_case, load_case_full

BASE_EPOCH = 1754762400  # dataset t0 (see scripts/generate_dataset.py)
DATA_DIR = Path(__file__).resolve().parents[2] / "data"

TRUNCATE_ORDER = [
    EvalCaseResult,
    EvalRun,
    AuditEvent,
    Notification,
    PolicyDecision,
    Escalation,
    RecoveryAction,
    AgentDecision,
    RecoveryCase,
    Payment,
    Customer,
    Merchant,
    WebhookEvent,
    RefCounter,
]


def load_dataset():
    events = [json.loads(line) for line in (DATA_DIR / "dataset_v1.jsonl").read_text().splitlines() if line.strip()]
    events.sort(key=lambda e: (e["created_at"], e["id"]))
    gt = {}
    for line in (DATA_DIR / "dataset_v1.ground_truth.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            gt[row["payment_id"]] = row
    return events, gt


async def reset_db(session):
    for model in TRUNCATE_ORDER:
        await session.execute(delete(model))


def compute_baselines(events: list[dict], gt: dict, seed: int) -> dict:
    """Deterministic do-nothing vs naive-retry-once baselines.

    Both are seeded and measured on the SAME dataset the agent processes, so the
    "agent's marginal value" is apples-to-apples. No policy, no diagnosis, no
    audit in either baseline — just the raw simulator roll.
    """
    # Collect one row per unique failed payment (S09 duplicates collapse via gt).
    rows: list[dict] = []
    for ev in events:
        if ev.get("event") != "payment.failed":
            continue
        pid = ev["payload"]["payment"]["entity"]["id"]
        if pid not in gt:
            continue
        row = gt[pid]
        # Amount: prefer the failed event's own payload.
        amount_minor = int(ev["payload"]["payment"]["entity"]["amount"])
        rows.append({
            "case_key": row["case_key"],
            "scenario": row["scenario"],
            "prob": float(row.get("simulated_capture_probability", 0.0)),
            "amount_minor": amount_minor,
        })
    # Deduplicate by case_key (S09 replayed deliveries share the same payment).
    seen: set[str] = set()
    unique = []
    for r in rows:
        if r["case_key"] in seen:
            continue
        seen.add(r["case_key"])
        unique.append(r)
    unique.sort(key=lambda r: r["case_key"])

    rng = random.Random(seed)

    def tally(subset: list[dict]) -> dict:
        count = sum(1 for r in subset if r["prob"] > 0 and r["scenario"] == "S08")
        amount = sum(r["amount_minor"] for r in subset if r["prob"] > 0 and r["scenario"] == "S08")
        return {"recovered_cases": count, "recovered_amount_minor": amount}

    # Do-nothing: only captured-webhook self-heals (S08) recover.
    do_nothing = tally(unique)

    # Naive retry once: blindly retry every failed payment once.
    recovered_cases = 0
    recovered_minor = 0
    for r in unique:
        if r["scenario"] == "S08":
            recovered_cases += 1
            recovered_minor += r["amount_minor"]
            continue
        if rng.random() < r["prob"]:
            recovered_cases += 1
            recovered_minor += r["amount_minor"]
    naive_retry = {"recovered_cases": recovered_cases, "recovered_amount_minor": recovered_minor}

    return {
        "do_nothing": do_nothing,
        "naive_retry_once": naive_retry,
    }


async def run(seed: int, keep_db: bool = False) -> dict:
    events, gt = load_dataset()
    report: dict = {"seed": seed, "events_total": len(events)}

    sim = SimulatedGatewayAdapter(seed=seed)
    cfg = PolicyConfig()
    deps = ExecutorDeps(simulated=sim, real=None, cfg=cfg)
    baselines = compute_baselines(events, gt, seed)

    async with session_scope() as session:
        if not keep_db:
            await reset_db(session)
        eval_run = EvalRun(
            run_ref=f"EVAL-{seed}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
            dataset_seed=seed,
            config_snapshot={"policy": cfg.to_dict(), "simulator_seed": seed, "llm": "fallback"},
        )
        session.add(eval_run)
        await session.flush()

        # Phase 1: ingest (dedupe exercised by replaying duplicates).
        dup_count = 0
        for ev in events:
            res = await ingest_event(
                session, ev, signature_valid=True,
                ground_truth=gt.get(ev["payload"]["payment"]["entity"]["id"]),
                is_simulated=True,
            )
            if res.duplicated:
                dup_count += 1
        report["duplicate_deliveries_skipped"] = dup_count
        n_cases = (await session.execute(select(func.count()).select_from(RecoveryCase))).scalar_one()
        report["cases_created"] = int(n_cases)

        # Phase 2: drive every case to a terminal state (deterministic order).
        # Each case gets its OWN virtual clock anchored at dataset t0: a shared
        # clock would leak fast-forwarded time (48h escalations) into later
        # cases' age calculations and mark them stale.
        t0 = datetime.fromtimestamp(BASE_EPOCH, tz=UTC)
        case_ids = (
            await session.execute(select(RecoveryCase.id).order_by(RecoveryCase.case_ref))
        ).scalars().all()
        for cid in case_ids:
            case = await load_case_full(session, cid)
            if case is None:
                continue
            await advance_case(session, case, deps, VirtualClock(t0))
        await session.flush()

        # Phase 3: score.
        report.update(await _score(session, eval_run))
        report["baselines"] = {
            "do_nothing": {
                **baselines["do_nothing"],
                "recovered_amount_inr": round(baselines["do_nothing"]["recovered_amount_minor"] / 100, 2),
            },
            "naive_retry_once": {
                **baselines["naive_retry_once"],
                "recovered_amount_inr": round(baselines["naive_retry_once"]["recovered_amount_minor"] / 100, 2),
            },
        }
        report["agent_marginal_inr"] = round(
            (report["recovered_amount_minor"] - baselines["naive_retry_once"]["recovered_amount_minor"]) / 100, 2
        )
        eval_run.finished_at = datetime.now(UTC)
        eval_run.report = report
        await session.flush()

    return report


async def _score(session, eval_run: EvalRun) -> dict:
    cases = (await session.execute(select(RecoveryCase).order_by(RecoveryCase.case_ref))).scalars().all()
    n = len(cases)

    diag_correct = strat_correct = 0
    outcomes: Counter = Counter()
    status_counts: Counter = Counter()
    recovered_minor = 0
    per_scenario: dict[str, dict] = defaultdict(lambda: {"n": 0, "diag_ok": 0, "strat_ok": 0, "recovered": 0})

    for c in cases:
        gt = c.ground_truth or {}
        exp_d = gt.get("expected_diagnosis")
        exp_s = gt.get("expected_strategy")
        act_d = c.diagnosis_class.value if c.diagnosis_class else None
        first_dec = (
            await session.execute(
                select(AgentDecision.strategy_id)
                .where(AgentDecision.case_id == c.id)
                .order_by(AgentDecision.created_at, AgentDecision.id)
                .limit(1)
            )
        ).scalar_one_or_none()
        act_s = first_dec if first_dec is not None else c.strategy_id
        d_ok, s_ok = act_d == exp_d, act_s == exp_s
        diag_correct += d_ok
        strat_correct += s_ok
        outcomes[c.outcome.value if c.outcome else "NONE"] += 1
        status_counts[c.status.value] += 1
        if c.status == CaseStatus.RECOVERED:
            recovered_minor += c.recovered_amount_minor
        scen = gt.get("scenario") or "?"
        per_scenario[scen]["n"] += 1
        per_scenario[scen]["diag_ok"] += d_ok
        per_scenario[scen]["strat_ok"] += s_ok
        per_scenario[scen]["recovered"] += c.status == CaseStatus.RECOVERED

        session.add(EvalCaseResult(
            run_id=eval_run.id,
            case_id=c.id,
            expected_diagnosis=exp_d,
            actual_diagnosis=act_d,
            expected_strategy=exp_s,
            actual_strategy=act_s,
            outcome=c.status.value,
            recovered_amount_minor=c.recovered_amount_minor,
        ))
    await session.flush()

    # Invariants.
    chain_ok = True
    for c in cases:
        if not await audit.validate_chain(session, c.id):
            chain_ok = False
    dup_groups = (
        await session.execute(
            select(func.count())
            .select_from(RecoveryAction)
            .group_by(RecoveryAction.idempotency_key)
            .having(func.count() > 1)
        )
    ).all()

    sim_actions = int((
        await session.execute(select(func.count()).select_from(RecoveryAction).where(RecoveryAction.execution_mode == ExecutionMode.SIMULATED))
    ).scalar_one())
    total_actions = int((await session.execute(select(func.count()).select_from(RecoveryAction))).scalar_one())
    policy_rows = int((
        await session.execute(select(func.count()).select_from(PolicyDecision))
    ).scalar_one())

    self_healed = outcomes.get("SELF_HEALED", 0)
    recovered = status_counts.get("RECOVERED", 0)
    return {
        "cases_total": n,
        "diagnosis_accuracy": round(diag_correct / n, 4) if n else 0.0,
        "strategy_accuracy": round(strat_correct / n, 4) if n else 0.0,
        "recovered_cases": recovered,
        "self_healed_cases": self_healed,
        "agent_recovered_cases": recovered - self_healed,
        "unrecovered_cases": status_counts.get("CLOSED_UNRECOVERED", 0),
        "escalated_cases": status_counts.get("ESCALATED", 0),
        "escalation_rate": round(status_counts.get("ESCALATED", 0) / n, 4) if n else 0.0,
        "recovered_amount_minor": recovered_minor,
        "recovered_amount_inr": round(recovered_minor / 100, 2),
        "status_counts": dict(status_counts),
        "audit_chain_valid_all_cases": chain_ok,
        "idempotency_violations": len(dup_groups),
        "actions_total": total_actions,
        "actions_simulated": sim_actions,
        "policy_decisions": policy_rows,
        "per_scenario": dict(sorted(per_scenario.items())),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--keep-db", action="store_true", help="do not truncate before the run")
    args = parser.parse_args()
    report = asyncio.run(run(args.seed, keep_db=args.keep_db))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
