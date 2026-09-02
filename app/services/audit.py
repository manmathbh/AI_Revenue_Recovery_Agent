"""Append-only, hash-chained audit log (DATA_MODEL.md audit_events).

Every event carries `prev_event_hash` -> `event_hash`; the chain is validated per
case. UPDATE/DELETE on audit_events is revoked for the app role (enforced by
migration/ops); code only ever INSERTs.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.enums import Actor
from app.db.models import AuditEvent


def _hash(prev_hash: str | None, *, case_id: str | None, actor: str, event_type: str, detail: dict) -> str:
    payload = json.dumps(
        {
            "case_id": str(case_id) if case_id else None,
            "actor": actor,
            "event_type": event_type,
            "detail": detail,
            "prev_event_hash": prev_hash,
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def append_event(
    session: AsyncSession,
    *,
    case_id: uuid.UUID | None,
    actor: Actor,
    event_type: str,
    detail: dict | None = None,
) -> AuditEvent:
    """Append an audit event, chaining onto the latest event for the case."""
    detail = detail or {}

    prev_hash: str | None = None
    if case_id is not None:
        row = await session.execute(
            select(AuditEvent.event_hash)
            .where(AuditEvent.case_id == case_id)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
            .limit(1)
        )
        prev_hash = row.scalar_one_or_none()

    event_hash = _hash(
        prev_hash,
        case_id=str(case_id) if case_id else None,
        actor=actor.value,
        event_type=event_type,
        detail=detail,
    )
    evt = AuditEvent(
        case_id=case_id,
        actor=actor,
        event_type=event_type,
        detail=detail,
        prev_event_hash=prev_hash,
        event_hash=event_hash,
    )
    session.add(evt)
    await session.flush()
    return evt


async def validate_chain(session: AsyncSession, case_id: uuid.UUID) -> bool:
    rows = await session.execute(
        select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.created_at, AuditEvent.id)
    )
    events = rows.scalars().all()
    prev: str | None = None
    for e in events:
        expected = _hash(
            prev,
            case_id=str(case_id),
            actor=e.actor.value,
            event_type=e.event_type,
            detail=e.detail,
        )
        if e.event_hash != expected or e.prev_event_hash != prev:
            return False
        prev = e.event_hash
    return True
