"""Alarms and ward-default alarm limits.

Acknowledging an alarm records who responded and when. It never changes the alarm state: an
acknowledged alarm whose condition is still present stays ACTIVE until the engine observes that
the condition has cleared.
"""

from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Query

from app.db import get_db
from app.errors import ApiError, forbidden, not_found
from app.routers._shared import page_params
from app.schemas.common import BedId
from app.schemas.requests import AckIn, ThresholdSetIn
from app.security import authz
from app.security.auth import Principal, get_principal, require
from app.security.context import RequestContext, get_context
from app.services import audit, simulation

router = APIRouter(tags=["alarms"])


@router.get("/alarms")
def list_alarms(
    state: Literal["active", "resolved", "all", "attention"] = "attention",
    severity: Literal["critical", "warning", "advisory", "all"] = "all",
    category: Literal["physiological", "technical", "all"] = "all",
    acknowledged: Literal["yes", "no", "all"] = "all",
    bed_id: BedId | None = None,
    page: int = Query(default=1, ge=1, le=1000),
    page_size: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(require("alarms:view")),
    conn: psycopg.Connection = Depends(get_db),
) -> dict:
    where = ["true"]
    params: dict = {}
    if state == "attention":  # active, or resolved but never acknowledged
        where.append("(a.state = 'active' or a.acknowledged_at is null)")
    elif state != "all":
        where.append("a.state = %(state)s")
        params["state"] = state
    if severity != "all":
        where.append("a.severity = %(severity)s")
        params["severity"] = severity
    if category != "all":
        where.append("a.category = %(category)s")
        params["category"] = category
    if acknowledged == "yes":
        where.append("a.acknowledged_at is not null")
    elif acknowledged == "no":
        where.append("a.acknowledged_at is null")
    if bed_id:
        where.append("a.bed_id = %(bed)s")
        params["bed"] = bed_id
    limit, offset = page_params(page, page_size)
    params.update({"limit": limit, "offset": offset})
    where_sql = " and ".join(where)  # fixed fragments only; values are bound
    show_names = principal.can("patients:view")
    total = conn.execute(f"select count(*) as n from public.alarms a where {where_sql}", params).fetchone()["n"]
    rows = conn.execute(
        f"""select a.id, a.monitor_id, a.bed_id, a.patient_id, a.type, a.category, a.severity, a.message, a.value,
                   a.threshold, a.state, a.raised_at, a.last_seen_at, a.resolved_at, a.acknowledged_at,
                   a.acknowledged_by_name, a.ack_note, p.first_name, p.last_name
            from public.alarms a left join public.patients p on p.id = a.patient_id
            where {where_sql}
            order by (a.state = 'active') desc,
                     case a.severity when 'critical' then 0 when 'warning' then 1 else 2 end,
                     a.raised_at desc
            limit %(limit)s offset %(offset)s""",
        params,
    ).fetchall()
    items = []
    for r in rows:
        item = dict(r)
        item["patient_name"] = f"{r['first_name']} {r['last_name']}" if show_names and r["first_name"] else None
        item.pop("first_name")
        item.pop("last_name")
        item["value"] = float(r["value"]) if r["value"] is not None else None
        item["threshold"] = float(r["threshold"]) if r["threshold"] is not None else None
        item["can_acknowledge"] = r["acknowledged_at"] is None and principal.can(authz.ack_permission(r["category"]))
        items.append(item)
    counts = conn.execute(
        """select count(*) filter (where state = 'active') as active,
                  count(*) filter (where state = 'active' and severity = 'critical') as critical,
                  count(*) filter (where acknowledged_at is null) as unacknowledged
           from public.alarms"""
    ).fetchone()
    return {"items": items, "total": total, "page": page, "page_size": limit, "counts": counts}


@router.post("/alarms/{alarm_id}/acknowledge")
def acknowledge(alarm_id: UUID, body: AckIn, principal: Principal = Depends(get_principal),
                conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    alarm = conn.execute("select id, category, state, acknowledged_at, bed_id, type, monitor_id from public.alarms where id = %s",
                         (alarm_id,)).fetchone()
    if alarm is None:
        raise not_found("Alarm")
    permission = authz.ack_permission(alarm["category"])
    if not principal.can(permission):
        audit.record(conn, "authz.denied", actor=principal, outcome="denied", entity_type="alarm",
                     entity_id=str(alarm_id), details={"permission": permission}, ctx=ctx)
        raise forbidden("Your role cannot acknowledge this type of alarm.")
    # Conditional update: protects against two users acknowledging at the same moment.
    row = conn.execute(
        """update public.alarms set acknowledged_at = now(), acknowledged_by = %s, acknowledged_by_name = %s,
               ack_note = %s
           where id = %s and acknowledged_at is null
           returning id, state, acknowledged_at""",
        (principal.id, principal.full_name, body.note or None, alarm_id),
    ).fetchone()
    if row is None:
        raise ApiError(409, "already_acknowledged", "This alarm was already acknowledged.")
    audit.record(conn, "alarm.acknowledge", actor=principal, entity_type="alarm", entity_id=str(alarm_id),
                 details={"type": alarm["type"], "state_after": row["state"]}, ctx=ctx)
    simulation.log_event(conn, "alarm_acknowledged",
                         f"{simulation.ALARM_LABELS[alarm['type']]} on {alarm['bed_id']} acknowledged by {principal.full_name}"
                         + (" - condition still present" if row["state"] == "active" else ""),
                         monitor_id=alarm["monitor_id"], actor_id=principal.id)
    return {
        "id": row["id"], "state": row["state"], "acknowledged_at": row["acknowledged_at"],
        "message": "Alarm acknowledged. It remains active until the condition clears."
        if row["state"] == "active" else "Alarm acknowledged.",
    }


@router.get("/thresholds/defaults")
def get_defaults(principal: Principal = Depends(require("thresholds:view")), conn: psycopg.Connection = Depends(get_db)) -> dict:
    defaults, overrides = simulation.load_thresholds(conn)
    patients_with_overrides = conn.execute(
        """select p.id, p.first_name, p.last_name, p.bed_id, t.parameter, t.low, t.high, t.enabled
           from public.thresholds t join public.patients p on p.id = t.patient_id
           order by p.bed_id, t.parameter"""
    ).fetchall()
    return {
        "defaults": defaults,
        "overrides": [{**r, "low": float(r["low"]) if r["low"] is not None else None,
                       "high": float(r["high"]) if r["high"] is not None else None} for r in patients_with_overrides],
        "can_edit_defaults": principal.can("thresholds:edit_default"),
        "can_edit_patient": principal.can("thresholds:edit_patient"),
    }


@router.put("/thresholds/defaults")
def set_defaults(body: ThresholdSetIn, principal: Principal = Depends(require("thresholds:edit_default")),
                 conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    for item in body.items:
        conn.execute(
            """insert into public.thresholds (patient_id, parameter, low, high, enabled, updated_by, updated_at)
               values (null, %s, %s, %s, %s, %s, now())
               on conflict (coalesce(patient_id, '00000000-0000-0000-0000-000000000000'::uuid), parameter)
               do update set low = excluded.low, high = excluded.high, enabled = excluded.enabled,
                             updated_by = excluded.updated_by, updated_at = now()""",
            (item.parameter, item.low, item.high, item.enabled, principal.id),
        )
    audit.record(conn, "thresholds.default_update", actor=principal, entity_type="thresholds", entity_id="ward",
                 details={"items": [i.model_dump() for i in body.items]}, ctx=ctx)
    simulation.log_event(conn, "thresholds", "Ward default alarm limits changed", actor_id=principal.id,
                         data={"parameters": [i.parameter for i in body.items]})
    defaults, _ = simulation.load_thresholds(conn)
    return {"defaults": defaults}
