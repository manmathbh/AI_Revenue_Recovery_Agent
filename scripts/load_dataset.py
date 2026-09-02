"""Load the frozen dataset into the DB (ingest only, no pipeline).

``make seed`` first regenerates data/dataset_v1.jsonl + ground truth, then this
script replays it through ingest_event (payments/customers/cases/self-heals).
The pipeline runs separately via scripts/batch.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.batch.run_eval import load_dataset, reset_db
from app.db.session import session_scope
from app.services.ingest import ingest_event

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


async def load() -> None:
    events, gt = load_dataset()
    async with session_scope() as session:
        await reset_db(session)
        dup = 0
        for ev in events:
            res = await ingest_event(
                session, ev, signature_valid=True,
                ground_truth=gt.get(ev["payload"]["payment"]["entity"]["id"]),
                is_simulated=True,
            )
            dup += int(res.duplicated)
        print(f"ingested {len(events)} events -> {len(gt)} cases, {dup} duplicate deliveries skipped")


def main() -> None:
    asyncio.run(load())


if __name__ == "__main__":
    main()
