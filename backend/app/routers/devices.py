"""Monitors (devices), bed assignment and maintenance tracking."""

from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Query

from app.db import get_db
from app.errors import ApiError, conflict, forbidden, not_found
from app.schemas.common import MonitorId, OptionalShortText
from app.schemas.requests import AssignIn, MaintenanceIn, MaintenanceUpdateIn, MonitorUpdateIn
from app.security.auth import Principal, get_principal, require
from app.security.context import RequestContext, get_context
from app.services import audit, simulation

router = APIRouter(tags=["devices"])

_MONITOR_COLUMNS = """m.id, m.serial_number, m.model, m.firmware, m.bed_id, m.status, m.scenario, m.battery_pct,
    m.connection, m.sensor_status, m.last_seen_at, m.last_maintenance_at, m.next_maintenance_due, m.updated_at"""


def _monitor_out(row: dict) -> dict:
    item = dict(row)
    item["battery_pct"] = float(item["battery_pct"])
    return item


@router.get("/devices")
def list_devices(
    q: OptionalShortText = "",
    status: Literal["active", "standby", "maintenance", "retired", "all"] = "all",
    issue: Literal["any", "offline", "low_battery", "sensor", "maintenance_due"] = "any",
    principal: Principal = Depends(require("devices:view")),
    conn: psycopg.Connection = Depends(get_db),
) -> dict:
    where = ["true"]
    params: dict = {}
    if q:
        where.append("(m.id ilike %(q)s or m.serial_number ilike %(q)s or m.model ilike %(q)s or m.bed_id ilike %(q)s)")
        params["q"] = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    if status != "all":
        where.append("m.status = %(status)s")
        params["status"] = status
    issue_sql = {
        "offline": "m.connection = 'offline'",
        "low_battery": "m.battery_pct < 20",
        "sensor": "m.sensor_status <> 'ok'",
        "maintenance_due": "m.next_maintenance_due < current_date",
    }
    if issue != "any":
        where.append(issue_sql[issue])
    rows = conn.execute(
        f"""select {_MONITOR_COLUMNS},
                   (select count(*) from public.maintenance_records r where r.monitor_id = m.id and r.status <> 'completed') as open_tickets,
                   (select count(*) from public.alarms a where a.monitor_id = m.id and a.state = 'active'
                      and a.category = 'technical') as technical_alarms
            from public.monitors m where {' and '.join(where)} order by m.id""",
        params,
    ).fetchall()
    return {"items": [_monitor_out(r) for r in rows]}


@router.get("/beds")
def list_beds(principal: Principal = Depends(require("devices:view")), conn: psycopg.Connection = Depends(get_db)) -> dict:
    rows = conn.execute(
        """select b.id, b.label, b.room, m.id as monitor_id, (p.id is not null) as occupied,
                  case when %s then p.first_name || ' ' || p.last_name end as patient_name
           from public.beds b left join public.monitors m on m.bed_id = b.id
           left join public.patients p on p.bed_id = b.id and p.status = 'admitted' order by b.id""",
        (principal.can("patients:view"),),
    ).fetchall()
    return {"items": rows}


@router.get("/devices/{monitor_id}")
def device_detail(monitor_id: MonitorId, principal: Principal = Depends(require("devices:view")),
                  conn: psycopg.Connection = Depends(get_db)) -> dict:
    m = conn.execute(f"select {_MONITOR_COLUMNS} from public.monitors m where m.id = %s", (monitor_id,)).fetchone()
    if m is None:
        raise not_found("Monitor")
    history = conn.execute(
        """select a.bed_id, a.assigned_at, a.unassigned_at, pa.full_name as assigned_by, pu.full_name as unassigned_by
           from public.monitor_assignments a left join public.profiles pa on pa.id = a.assigned_by
           left join public.profiles pu on pu.id = a.unassigned_by
           where a.monitor_id = %s order by a.assigned_at desc limit 20""",
        (monitor_id,),
    ).fetchall()
    maintenance = conn.execute(
        """select id, type, status, description, resolution, opened_by_name, completed_by_name, opened_at, completed_at
           from public.maintenance_records where monitor_id = %s order by opened_at desc limit 50""",
        (monitor_id,),
    ).fetchall()
    alarms = conn.execute(
        """select id, type, category, severity, message, state, raised_at, acknowledged_at from public.alarms
           where monitor_id = %s and category = 'technical' order by raised_at desc limit 20""",
        (monitor_id,),
    ).fetchall()
    return {**_monitor_out(m), "assignments": history, "maintenance": maintenance, "technical_alarms": alarms}


@router.post("/devices/{monitor_id}/assign")
def assign(monitor_id: MonitorId, body: AssignIn, principal: Principal = Depends(require("devices:assign")),
           conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    m = conn.execute("select id, bed_id, status from public.monitors where id = %s for update", (monitor_id,)).fetchone()
    if m is None:
        raise not_found("Monitor")
    if m["status"] in ("maintenance", "retired"):
        raise conflict(f"{monitor_id} is in {m['status']} and cannot be assigned to a bed.")
    if m["bed_id"] == body.bed_id:
        raise conflict(f"{monitor_id} is already assigned to {body.bed_id}.")
    if m["bed_id"] is not None:
        raise conflict(f"{monitor_id} is assigned to {m['bed_id']}. Unassign it first.")
    bed = conn.execute("select id from public.beds where id = %s", (body.bed_id,)).fetchone()
    if bed is None:
        raise not_found("Bed")
    other = conn.execute("select id from public.monitors where bed_id = %s", (body.bed_id,)).fetchone()
    if other:
        raise conflict(f"{body.bed_id} already has {other['id']}. Unassign it first.")
    patient = conn.execute("select id from public.patients where bed_id = %s and status = 'admitted'",
                           (body.bed_id,)).fetchone()
    conn.execute(
        """update public.monitors set bed_id = %s, status = 'active', connection = 'online', last_seen_at = (
               select sim_time from public.sim_state where id = 1), updated_at = now() where id = %s""",
        (body.bed_id, monitor_id),
    )
    conn.execute(
        "insert into public.monitor_assignments (monitor_id, bed_id, patient_id, assigned_by) values (%s, %s, %s, %s)",
        (monitor_id, body.bed_id, patient["id"] if patient else None, principal.id),
    )
    audit.record(conn, "device.assign", actor=principal, entity_type="monitor", entity_id=monitor_id,
                 details={"bed_id": body.bed_id}, ctx=ctx)
    simulation.log_event(conn, "assignment", f"{monitor_id} assigned to {body.bed_id} by {principal.full_name}",
                         monitor_id=monitor_id, actor_id=principal.id, data={"bed_id": body.bed_id})
    return {"ok": True, "monitor_id": monitor_id, "bed_id": body.bed_id}


@router.post("/devices/{monitor_id}/unassign")
def unassign(monitor_id: MonitorId, principal: Principal = Depends(require("devices:assign")),
             conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    m = conn.execute("select id, bed_id from public.monitors where id = %s for update", (monitor_id,)).fetchone()
    if m is None:
        raise not_found("Monitor")
    if m["bed_id"] is None:
        raise conflict(f"{monitor_id} is not assigned to a bed.")
    resolved = simulation.resolve_monitor_alarms(conn, monitor_id, "monitor unassigned")
    conn.execute("update public.monitors set bed_id = null, status = 'standby', updated_at = now() where id = %s",
                 (monitor_id,))
    conn.execute(
        """update public.monitor_assignments set unassigned_at = now(), unassigned_by = %s
           where monitor_id = %s and unassigned_at is null""",
        (principal.id, monitor_id),
    )
    audit.record(conn, "device.unassign", actor=principal, entity_type="monitor", entity_id=monitor_id,
                 details={"bed_id": m["bed_id"], "alarms_closed": resolved}, ctx=ctx)
    simulation.log_event(conn, "assignment", f"{monitor_id} removed from {m['bed_id']} by {principal.full_name}",
                         monitor_id=monitor_id, actor_id=principal.id, data={"bed_id": m["bed_id"]})
    return {"ok": True}


@router.patch("/devices/{monitor_id}")
def update_device(monitor_id: MonitorId, body: MonitorUpdateIn, principal: Principal = Depends(require("devices:manage")),
                  conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    m = conn.execute("select id, bed_id, status from public.monitors where id = %s for update", (monitor_id,)).fetchone()
    if m is None:
        raise not_found("Monitor")
    if body.status and body.status != m["status"]:
        if body.status in ("maintenance", "retired", "standby") and m["bed_id"]:
            raise conflict(f"Unassign {monitor_id} from {m['bed_id']} before changing its status to {body.status}.")
        if body.status == "active" and not m["bed_id"]:
            raise conflict("Assign the monitor to a bed to activate it.")
        conn.execute("update public.monitors set status = %s, updated_at = now() where id = %s", (body.status, monitor_id))
    if body.next_maintenance_due:
        conn.execute("update public.monitors set next_maintenance_due = %s, updated_at = now() where id = %s",
                     (body.next_maintenance_due, monitor_id))
    audit.record(conn, "device.update", actor=principal, entity_type="monitor", entity_id=monitor_id,
                 details=body.model_dump(mode="json", exclude_none=True), ctx=ctx)
    return {"ok": True}


@router.post("/devices/{monitor_id}/maintenance", status_code=201)
def open_ticket(monitor_id: MonitorId, body: MaintenanceIn, principal: Principal = Depends(get_principal),
                conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    needed = "maintenance:report" if body.type == "issue_report" else "maintenance:manage"
    if not principal.can(needed):
        audit.record(conn, "authz.denied", actor=principal, outcome="denied", entity_type="monitor",
                     entity_id=monitor_id, details={"permission": needed}, ctx=ctx)
        raise forbidden("Your role can report issues but not schedule maintenance work.")
    if conn.execute("select 1 from public.monitors where id = %s", (monitor_id,)).fetchone() is None:
        raise not_found("Monitor")
    row = conn.execute(
        """insert into public.maintenance_records (monitor_id, type, description, opened_by, opened_by_name)
           values (%s, %s, %s, %s, %s) returning id, opened_at""",
        (monitor_id, body.type, body.description, principal.id, principal.full_name),
    ).fetchone()
    audit.record(conn, "maintenance.open", actor=principal, entity_type="monitor", entity_id=monitor_id,
                 details={"ticket": str(row["id"]), "type": body.type}, ctx=ctx)
    simulation.log_event(conn, "maintenance", f"{body.type.replace('_', ' ').capitalize()} opened for {monitor_id}",
                         monitor_id=monitor_id, actor_id=principal.id)
    return {"id": row["id"], "opened_at": row["opened_at"]}


@router.get("/maintenance")
def list_maintenance(status: Literal["open", "in_progress", "completed", "all", "pending"] = "pending",
                     page_size: int = Query(default=50, ge=1, le=100),
                     principal: Principal = Depends(require("devices:view")),
                     conn: psycopg.Connection = Depends(get_db)) -> dict:
    where = "true"
    params: dict = {"limit": page_size}
    if status == "pending":
        where = "r.status <> 'completed'"
    elif status != "all":
        where = "r.status = %(status)s"
        params["status"] = status
    rows = conn.execute(
        f"""select r.id, r.monitor_id, r.type, r.status, r.description, r.resolution, r.opened_by_name,
                   r.completed_by_name, r.opened_at, r.completed_at, m.bed_id
            from public.maintenance_records r join public.monitors m on m.id = r.monitor_id
            where {where} order by r.opened_at desc limit %(limit)s""",
        params,
    ).fetchall()
    return {"items": rows}


@router.patch("/maintenance/{ticket_id}")
def update_ticket(ticket_id: UUID, body: MaintenanceUpdateIn, principal: Principal = Depends(require("maintenance:manage")),
                  conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    ticket = conn.execute("select id, monitor_id, status, opened_by from public.maintenance_records where id = %s for update",
                          (ticket_id,)).fetchone()
    if ticket is None:
        raise not_found("Maintenance record")
    if ticket["status"] == "completed":
        raise conflict("This maintenance record is already completed.")
    if body.status == "completed" and not body.resolution:
        raise ApiError(422, "validation_error", "Describe the work done before completing the record.")
    conn.execute(
        """update public.maintenance_records set status = %s, resolution = nullif(%s, ''),
               completed_by = case when %s = 'completed' then %s end,
               completed_by_name = case when %s = 'completed' then %s end,
               completed_at = case when %s = 'completed' then now() end
           where id = %s""",
        (body.status, body.resolution, body.status, principal.id, body.status, principal.full_name, body.status,
         ticket_id),
    )
    if body.status == "completed":
        conn.execute(
            """update public.monitors set last_maintenance_at = now(),
                   next_maintenance_due = greatest(coalesce(next_maintenance_due, current_date), current_date + 180)
               where id = %s""",
            (ticket["monitor_id"],),
        )
    audit.record(conn, "maintenance.update", actor=principal, entity_type="maintenance", entity_id=str(ticket_id),
                 details={"status": body.status}, ctx=ctx)
    simulation.log_event(conn, "maintenance", f"Maintenance on {ticket['monitor_id']} set to {body.status.replace('_', ' ')}",
                         monitor_id=ticket["monitor_id"], actor_id=principal.id)
    return {"ok": True}
