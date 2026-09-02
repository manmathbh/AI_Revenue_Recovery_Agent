"""Live worker loop: claim active cases (SKIP LOCKED) and advance them.

Batch/deterministic behavior lives in app.batch.run_eval; this is the always-on
service for real webhook-driven traffic. A virtual clock is NOT used here —
policy WAIT verdicts leave the case parked and re-claimed after the poll delay.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.enums import ACTIVE_CASE_STATUSES
from app.db.models import RecoveryCase
from app.db.session import session_scope
from app.executors.actions import ExecutorDeps
from app.integrations.razorpay import RazorpayAdapter
from app.integrations.simulated_gateway import SimulatedGatewayAdapter
from app.policy.config import PolicyConfig
from app.services.pipeline import VirtualClock, advance_case, load_case_full

log = logging.getLogger("recoup.worker")

POLL_INTERVAL_S = 5.0
CLAIM_BATCH = 20


class RealtimeClock(VirtualClock):
    def now(self) -> datetime:
        return datetime.now(UTC)

    def advance_minutes(self, minutes: int) -> None:  # never fast-forward live time
        pass


async def build_deps() -> ExecutorDeps:
    from app.config import get_settings

    s = get_settings()
    real = None
    if s.razorpay_key_id and not s.razorpay_key_id.startswith("rzp_test_dummy"):
        real = RazorpayAdapter(s)
    return ExecutorDeps(
        simulated=SimulatedGatewayAdapter(seed=42),
        real=real,
        cfg=PolicyConfig(),
        fast_forward=False,
    )


async def tick(deps: ExecutorDeps) -> int:
    """Claim and advance up to CLAIM_BATCH cases. Returns cases processed."""
    processed = 0
    clock = RealtimeClock(datetime.now(UTC))
    async with session_scope() as session:
        ids = (
            await session.execute(
                select(RecoveryCase.id)
                .where(RecoveryCase.status.in_(list(ACTIVE_CASE_STATUSES)))
                .order_by(RecoveryCase.created_at)
                .limit(CLAIM_BATCH)
            )
        ).scalars().all()
        for cid in ids:
            case = await load_case_full(session, cid)
            if case is None:
                continue
            await advance_case(session, case, deps, clock)
            processed += 1
    return processed


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    deps = await build_deps()
    log.info("worker started (real gateway=%s)", deps.real is not None)
    while True:
        try:
            n = await tick(deps)
            if n == 0:
                await asyncio.sleep(POLL_INTERVAL_S)
        except Exception:
            log.exception("worker tick failed")
            await asyncio.sleep(POLL_INTERVAL_S)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "batch":
        # `python -m app.worker batch [--seed N]` -> deterministic batch eval.
        import json

        from app.batch.run_eval import run

        seed = 42
        if "--seed" in sys.argv:
            seed = int(sys.argv[sys.argv.index("--seed") + 1])
        report = asyncio.run(run(seed))
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        asyncio.run(main())
