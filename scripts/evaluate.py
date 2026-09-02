"""Show the latest evaluation report (``make evaluate``).

Reads the most recent eval_runs row and prints the stored report, so judges can
re-open a completed run without re-running it.
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import desc, select

from app.db.models import EvalRun
from app.db.session import session_scope


async def show_latest() -> dict | None:
    async with session_scope() as session:
        row = await session.execute(select(EvalRun).order_by(desc(EvalRun.started_at)).limit(1))
        run = row.scalar_one_or_none()
        if run is None:
            print("No evaluation run found. Run `make batch` first.")
            return None
        print(f"run_ref: {run.run_ref}  seed: {run.dataset_seed}  started: {run.started_at.isoformat()}")
        report = run.report or {}
        print(json.dumps(report, indent=2, sort_keys=True))
        return report


def main() -> None:
    asyncio.run(show_latest())


if __name__ == "__main__":
    main()
