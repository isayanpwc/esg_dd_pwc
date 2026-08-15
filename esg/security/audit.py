"""
Append-only, hash-chained audit log.

An ESG due-diligence file is evidence. If a finding is challenged months
later, "the tool says so" is worth nothing unless we can show the record was
not edited after the fact. Each entry commits to its predecessor, so removing
or altering any row breaks verification from that point forward.

Application code can only append. On Postgres, UPDATE and DELETE are also
blocked by trigger (migration 0002), so a compromised application account
cannot rewrite history either.
"""

import hashlib
import json
from datetime import datetime

from sqlalchemy import select

from esg.db.models import AuditEvent
from esg import clock

GENESIS = "0" * 64


def _digest(prev_hash, payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(f"{prev_hash}|{canonical}".encode("utf-8")).hexdigest()


def _tip(session):
    row = session.execute(
        select(AuditEvent.entry_hash)
        .order_by(AuditEvent.seq.desc())
        .limit(1)
        .execution_options(esg_skip_scope=True)
    ).scalar()
    return row or GENESIS


def record(session, actor, action, entity_type=None, entity_id=None,
           deal_id=None, detail=None):
    """Append one event. Returns the created AuditEvent (not yet committed).

    Deliberately takes the caller's session so the audit row commits in the
    same transaction as the change it describes — an action that rolls back
    leaves no misleading audit trail, and one that commits cannot fail to be
    logged.
    """
    occurred_at = clock.now()
    payload = {
        "occurred_at": occurred_at.isoformat(),
        "actor": actor,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "deal_id": deal_id,
        "detail": detail if isinstance(detail, str) else json.dumps(detail, default=str)
        if detail is not None else None,
    }
    prev_hash = _tip(session)
    event = AuditEvent(
        occurred_at=occurred_at,
        actor=actor,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        deal_id=deal_id,
        detail=payload["detail"],
        prev_hash=prev_hash,
        entry_hash=_digest(prev_hash, payload),
    )
    session.add(event)
    session.flush()
    return event


def verify_chain(session, limit=None):
    """Recompute the chain. Returns (ok, list_of_problems)."""
    stmt = select(AuditEvent).order_by(AuditEvent.seq).execution_options(
        esg_skip_scope=True
    )
    if limit:
        stmt = stmt.limit(limit)

    problems = []
    expected_prev = GENESIS
    for event in session.execute(stmt).scalars():
        payload = {
            "occurred_at": event.occurred_at.isoformat(),
            "actor": event.actor,
            "action": event.action,
            "entity_type": event.entity_type,
            "entity_id": event.entity_id,
            "deal_id": event.deal_id,
            "detail": event.detail,
        }
        if event.prev_hash != expected_prev:
            problems.append(
                f"seq={event.seq}: prev_hash {event.prev_hash[:12]}… "
                f"does not match previous entry {expected_prev[:12]}… "
                "(an earlier row was altered or removed)"
            )
        recomputed = _digest(event.prev_hash, payload)
        if recomputed != event.entry_hash:
            problems.append(
                f"seq={event.seq}: contents do not match entry_hash "
                "(this row was edited in place)"
            )
        expected_prev = event.entry_hash

    return (not problems), problems
