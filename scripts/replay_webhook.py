"""Replay a stored webhook delivery (Demo 4 — duplicate webhook attack).

Re-sends the SAME ``payment.failed`` event N times. The ingest layer must open
exactly ONE case and skip the rest as duplicates (idempotency ledger).

Usage:
    python scripts/replay_webhook.py --case S09-001 --times 3
    python scripts/replay_webhook.py --case S01-001 --times 3 --url http://localhost:8000

Default (--url unset) ingests directly against the DB; with --url it POSTs the
raw body to the live API (signature computed with the configured webhook secret).
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
from pathlib import Path

import httpx

from app.services.ingest import ingest_event

DATA_DIR = Path(__file__).resolve().parents[1] / "data"


def _find_event(case_key: str) -> tuple[dict, dict | None]:
    events = [json.loads(line) for line in (DATA_DIR / "dataset_v1.jsonl").read_text().splitlines() if line.strip()]
    gt = {}
    for line in (DATA_DIR / "dataset_v1.ground_truth.jsonl").read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            gt[row["payment_id"]] = row
    for ev in events:
        if ev.get("event") != "payment.failed":
            continue
        pid = ev["payload"]["payment"]["entity"]["id"]
        row = gt.get(pid)
        if row and row.get("case_key") == case_key:
            return ev, row
    raise SystemExit(f"case {case_key} not found in dataset")


def _sign(raw: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


async def _direct(ev: dict, gt: dict | None) -> None:
    from app.db.session import session_scope

    async with session_scope() as session:
        res = await ingest_event(session, ev, signature_valid=True, ground_truth=gt, is_simulated=True)
        tag = "DUPLICATE" if res.duplicated else "CREATED"
        print(f"  direct ingest -> {tag} case_ref={res.case_ref or '-'}")


async def _via_api(ev: dict, url: str, secret: str) -> None:
    body = json.dumps(ev).encode()
    sig = _sign(body, secret)
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{url.rstrip('/')}/webhooks/razorpay",
            content=body,
            headers={"Content-Type": "application/json", "X-Razorpay-Signature": sig},
        )
        print(f"  POST {resp.status_code} -> {resp.json()}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", default="S09-001")
    parser.add_argument("--times", type=int, default=3)
    parser.add_argument("--url", default=None, help="live API base URL (optional)")
    args = parser.parse_args()

    ev, gt = _find_event(args.case)
    print(f"replaying {args.case} x{args.times} (event {ev['id']})")

    if args.url:
        from app.config import get_settings

        secret = get_settings().razorpay_webhook_secret
        for _ in range(args.times):
            await _via_api(ev, args.url, secret)
    else:
        for _ in range(args.times):
            await _direct(ev, gt)

    print("done — expect exactly ONE case, the rest absorbed as duplicates")


if __name__ == "__main__":
    asyncio.run(main())
