"""Simulation console: scenarios, presets, advancing time, event inspector, integration outbox, reset."""

from datetime import UTC, datetime
from typing import Literal

import psycopg
from fastapi import APIRouter, Depends, Query

from app.config import get_settings
from app.db import get_db
from app.errors import not_found
from app.schemas.common import MonitorId
from app.schemas.requests import AdvanceIn, ResetIn, ScenarioIn
from app.security import ratelimit
from app.security.auth import Principal, require
from app.security.context import RequestContext, get_context
from app.services import audit, seed, simulation, supabase

router = APIRouter(prefix="/simulation", tags=["simulation"])

PresetName = Literal["all_normal", "desaturation", "battery_round", "sensor_trouble", "network_outage", "busy_shift"]


@router.get("/state")
def state(principal: Principal = Depends(require("simulation:view")), conn: psycopg.Connection = Depends(get_db)) -> dict:
    sim = conn.execute("select tick, sim_time, seed, tick_seconds, last_advanced_at from public.sim_state where id = 1").fetchone()
    monitors = conn.execute(
        """select id, bed_id, status, scenario, battery_pct, connection, sensor_status, last_seen_at
           from public.monitors order by id"""
    ).fetchall()
    return {
        "state": sim,
        "monitors": [{**m, "battery_pct": float(m["battery_pct"])} for m in monitors],
        "scenarios": [{"id": k, "label": v} for k, v in simulation.SCENARIO_LABELS.items()],
        "presets": [{"id": k, "label": v["label"], "description": v["description"]} for k, v in simulation.PRESETS.items()],
        "can_reset": principal.can("simulation:reset"),
    }


@router.post("/advance")
def advance(body: AdvanceIn, principal: Principal = Depends(require("simulation:advance")),
            conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    ratelimit.hit(conn, f"sim-advance:{principal.id}", limit=60, window_seconds=60)
    if body.source == "auto":
        last = conn.execute("select last_advanced_at from public.sim_state where id = 1").fetchone()
        if last and last["last_advanced_at"] and (datetime.now(UTC) - last["last_advanced_at"]).total_seconds() < 3:
            return {"skipped": True, "reason": "Another session advanced the simulation moments ago."}
    result = simulation.advance(conn, body.steps, get_settings().data_retention_days)
    if body.source == "manual" or result["alarms_raised"]:
        simulation.log_event(conn, "advance", f"Simulation advanced {body.steps} tick(s) to t={result['tick']}"
                             f" - {result['alarms_raised']} new alarm(s)", actor_id=principal.id,
                             data={"steps": body.steps, "source": body.source})
    if body.source == "manual":
        audit.record(conn, "simulation.advance", actor=principal, details={"steps": body.steps}, ctx=ctx)
    return {"skipped": False, **result}


@router.put("/monitors/{monitor_id}/scenario")
def set_scenario(monitor_id: MonitorId, body: ScenarioIn, principal: Principal = Depends(require("simulation:control")),
                 conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    row = simulation.set_scenario(conn, monitor_id, body.scenario, actor_id=principal.id)
    if row is None:
        raise not_found("Monitor")
    audit.record(conn, "simulation.scenario", actor=principal, entity_type="monitor", entity_id=monitor_id,
                 details={"scenario": body.scenario}, ctx=ctx)
    return {"monitor_id": monitor_id, "scenario": body.scenario}


@router.post("/presets/{preset}")
def apply_preset(preset: PresetName, principal: Principal = Depends(require("simulation:control")),
                 conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    mapping = simulation.PRESETS[preset]["monitors"]
    for row in conn.execute("select id, scenario from public.monitors order by id").fetchall():
        wanted = mapping.get(row["id"], "normal")
        if row["scenario"] != wanted:
            simulation.set_scenario(conn, row["id"], wanted, actor_id=principal.id)
    simulation.log_event(conn, "preset", f"Scenario preset '{simulation.PRESETS[preset]['label']}' applied",
                         actor_id=principal.id, data={"preset": preset})
    audit.record(conn, "simulation.preset", actor=principal, details={"preset": preset}, ctx=ctx)
    return {"preset": preset}


@router.get("/events")
def events(
    kind: Literal["all", "alarm_raised", "alarm_escalated", "alarm_resolved", "alarm_acknowledged", "scenario_change",
                  "preset", "advance",
                  "assignment", "maintenance", "integration", "thresholds", "reset"] = "all",
    monitor_id: MonitorId | None = None,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(require("simulation:view")),
    conn: psycopg.Connection = Depends(get_db),
) -> dict:
    where = ["true"]
    params: dict = {"limit": limit}
    if kind != "all":
        where.append("e.kind = %(kind)s")
        params["kind"] = kind
    if monitor_id:
        where.append("e.monitor_id = %(monitor)s")
        params["monitor"] = monitor_id
    if before_id:
        where.append("e.id < %(before)s")
        params["before"] = before_id
    rows = conn.execute(
        f"""select e.id, e.tick, e.occurred_at, e.kind, e.monitor_id, e.message, e.data, p.full_name as actor
            from public.sim_events e left join public.profiles p on p.id = e.actor_id
            where {' and '.join(where)} order by e.id desc limit %(limit)s""",
        params,
    ).fetchall()
    return {"items": rows, "next_before_id": rows[-1]["id"] if len(rows) == limit else None}


@router.get("/outbox")
def outbox(principal: Principal = Depends(require("simulation:view")), conn: psycopg.Connection = Depends(get_db)) -> dict:
    rows = conn.execute(
        """select id, channel, recipient, subject, status, created_at from public.integration_outbox
           order by id desc limit 50"""
    ).fetchall()
    return {"items": rows}


@router.post("/reset")
def reset(body: ResetIn, principal: Principal = Depends(require("simulation:reset")),
          conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    """Destructive: requires the admin role, AAL2 (when enabled) and the typed confirmation 'RESET'."""
    ratelimit.hit(conn, f"sim-reset:{principal.id}", limit=5, window_seconds=600)
    stale_files = seed.reset_demo_data(conn)
    try:
        supabase.storage_remove("reports", stale_files)
    except supabase.SupabaseError:
        pass
    audit.record(conn, "simulation.reset", actor=principal, details={"confirm": body.confirm}, ctx=ctx)
    return {"ok": True, "message": "Demo data was reset to its initial state."}
