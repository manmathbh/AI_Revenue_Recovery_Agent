"""Live recovered-revenue ticker (Demo 1).

Polls the API dashboard and prints a running total; the number "ticks up" the
moment a recovery is verified end-to-end. Point at the live API or fall back to
the DB directly (no server needed).

Usage:
    python scripts/watch.py               # talks to http://localhost:8000
    python scripts/watch.py --db          # reads the DB directly (no server)
    python scripts/watch.py --interval 1  # faster polling
"""

from __future__ import annotations

import argparse
import asyncio

import httpx
from sqlalchemy import func, select

from app.db.models import RecoveryCase
from app.db.session import session_scope


async def _db_stats() -> dict:
    async with session_scope() as session:
        recovered = (
            await session.execute(select(func.count()).select_from(RecoveryCase).where(RecoveryCase.status == "RECOVERED"))
        ).scalar_one()
        amount = (
            await session.execute(select(func.coalesce(func.sum(RecoveryCase.recovered_amount_minor), 0)))
        ).scalar_one()
    return {"recovered_cases": int(recovered), "recovered_amount_inr": round(amount / 100, 2)}


async def _api_stats(url: str) -> dict:
    async with httpx.AsyncClient(timeout=5.0) as client:
        d = (await client.get(f"{url.rstrip('/')}/api/dashboard")).json()
    return {"recovered_cases": d["recovered_cases"], "recovered_amount_inr": d["recovered_amount_inr"]}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", action="store_true", help="read the DB directly (no server)")
    parser.add_argument("--url", default="http://localhost:8000")
    parser.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args()

    last = (0, 0.0)
    print("watching recovered revenue… (Ctrl-C to stop)")
    while True:
        s = await (_db_stats() if args.db else _api_stats(args.url))
        cur = (s["recovered_cases"], s["recovered_amount_inr"])
        if cur != last:
            delta = cur[1] - last[1]
            arrow = f"  +₹{delta:,.2f}" if delta > 0 else ""
            print(f"  ₹{cur[1]:>12,.2f}  ·  {cur[0]:>3} cases recovered{arrow}")
            last = cur
        await asyncio.sleep(args.interval)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
