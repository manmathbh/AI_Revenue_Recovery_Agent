"""Batch runner entrypoint: ``make batch`` / ``python scripts/batch.py``.

Runs the full evaluation against the seeded dataset and prints a human-readable
report (the numbers DEMO_PLAN.md Demo 5 shows). Wrapper over app.batch.run_eval.
"""

from __future__ import annotations

import asyncio
import json

from app.batch.run_eval import run


def _print_report(r: dict) -> None:
    b = r.get("baselines", {})
    dn = b.get("do_nothing", {})
    nr = b.get("naive_retry_once", {})
    print("=" * 62)
    print(f"RECOUP  —  batch evaluation (seed {r['seed']}, {r['cases_total']} cases)")
    print("=" * 62)
    print(f"  diagnosis accuracy   : {r['diagnosis_accuracy']*100:.1f}%  (target >= 85%)")
    print(f"  strategy accuracy    : {r['strategy_accuracy']*100:.1f}%  (target >= 80%)")
    print(f"  recovered cases      : {r['recovered_cases']} ({r['self_healed_cases']} self-healed, {r['agent_recovered_cases']} agent-driven)")
    print(f"  recovered amount     : ₹{r['recovered_amount_inr']:,.2f}")
    print(f"  escalated (human)    : {r['escalated_cases']}  ({r['escalation_rate']*100:.1f}%)")
    print("-" * 62)
    print("  BASELINES vs AGENT")
    print(f"    do-nothing         : ₹{dn.get('recovered_amount_inr', 0):,.2f}  ({dn.get('recovered_cases', 0)} cases)")
    print(f"    naive retry-once   : ₹{nr.get('recovered_amount_inr', 0):,.2f}  ({nr.get('recovered_cases', 0)} cases)")
    print(f"    agent marginal     : ₹{r.get('agent_marginal_inr', 0):,.2f}")
    print("-" * 62)
    print("  SAFETY INVARIANTS")
    print(f"    audit chain valid  : {r['audit_chain_valid_all_cases']}")
    print(f"    idempotency viol.  : {r['idempotency_violations']}  (must be 0)")
    print(f"    duplicate deliveries absorbed : {r['duplicate_deliveries_skipped']}")
    print("=" * 62)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--json", action="store_true", help="emit raw JSON")
    args = parser.parse_args()
    report = asyncio.run(run(args.seed))
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_report(report)


if __name__ == "__main__":
    main()
