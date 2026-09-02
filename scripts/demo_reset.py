"""Reset every app table to a clean slate (``make demo-reset``).

Use before a fresh demo run so counters start at RC-000001 and the dashboard
produces pristine numbers. Preserves schema (no migrations run).
"""

from __future__ import annotations

import asyncio

from app.batch.run_eval import reset_db
from app.db.session import session_scope


async def main() -> None:
    async with session_scope() as session:
        await reset_db(session)
    print("demo state reset")


if __name__ == "__main__":
    asyncio.run(main())
