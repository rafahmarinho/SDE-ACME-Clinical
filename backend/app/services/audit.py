"""Tamper-evident audit trail.

Each record is chained to the previous one with HMAC-SHA256 (key: AUDIT_HMAC_KEY), which makes
deletion, reordering or modification detectable by `verify_chain`. The API role can only INSERT
and SELECT this table. Details must never contain secrets, passwords, tokens or clinical free text.
"""

from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.security.context import RequestContext
from app.security.crypto import audit_hash

GENESIS = "0" * 64
_LOCK_ID = 7426001

FORBIDDEN_DETAIL_KEYS = {"password", "token", "access_token", "refresh_token", "secret", "body", "note"}


def _clean(details: dict[str, Any] | None) -> dict[str, Any]:
    if not details:
        return {}
    return {k: v for k, v in details.items() if k.lower() not in FORBIDDEN_DETAIL_KEYS}


def record(
    conn: psycopg.Connection,
    action: str,
    *,
    actor: Any = None,
    actor_email: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    outcome: str = "success",
    details: dict[str, Any] | None = None,
    ctx: RequestContext | None = None,
) -> None:
    conn.execute("select pg_advisory_xact_lock(%s)", (_LOCK_ID,))
    row = conn.execute("select hash from public.audit_log order by id desc limit 1").fetchone()
    prev = row["hash"] if row else GENESIS
    rec = {
        "created_at": datetime.now(UTC).isoformat(),
        "actor_id": str(actor.id) if actor else None,
        "actor_email": actor.email if actor else actor_email,
        "actor_role": actor.role if actor else None,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "outcome": outcome,
        "details": _clean(details),
        "ip": ctx.ip if ctx else None,
        "user_agent": ctx.user_agent if ctx else None,
        "request_id": ctx.request_id if ctx else None,
    }
    digest = audit_hash(prev, rec)
    conn.execute(
        """insert into public.audit_log (created_at, actor_id, actor_email, actor_role, action, entity_type,
               entity_id, outcome, details, ip, user_agent, request_id, prev_hash, hash)
           values (%(created_at)s, %(actor_id)s, %(actor_email)s, %(actor_role)s, %(action)s, %(entity_type)s,
               %(entity_id)s, %(outcome)s, %(details)s, %(ip)s, %(user_agent)s, %(request_id)s,
               %(prev)s, %(hash)s)""",
        {**rec, "details": Jsonb(rec["details"]), "prev": prev, "hash": digest},
    )


def verify_chain(conn: psycopg.Connection) -> dict[str, Any]:
    prev = GENESIS
    checked = 0
    for row in conn.execute(
        """select id, created_at, actor_id, actor_email, actor_role, action, entity_type, entity_id, outcome,
                  details, ip, user_agent, request_id, prev_hash, hash
           from public.audit_log order by id"""
    ):
        rec = {
            "created_at": row["created_at"].astimezone(UTC).isoformat(),
            "actor_id": str(row["actor_id"]) if row["actor_id"] else None,
            "actor_email": row["actor_email"],
            "actor_role": row["actor_role"],
            "action": row["action"],
            "entity_type": row["entity_type"],
            "entity_id": row["entity_id"],
            "outcome": row["outcome"],
            "details": row["details"],
            "ip": row["ip"],
            "user_agent": row["user_agent"],
            "request_id": row["request_id"],
        }
        if row["prev_hash"] != prev or audit_hash(prev, rec) != row["hash"]:
            return {"valid": False, "checked": checked, "broken_at": row["id"]}
        prev = row["hash"]
        checked += 1
    return {"valid": True, "checked": checked, "broken_at": None}
