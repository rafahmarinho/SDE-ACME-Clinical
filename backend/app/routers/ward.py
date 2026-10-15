"""Ward overview and live monitoring (central station)."""

import zlib

import psycopg
from fastapi import APIRouter, Depends, Query

from app.db import get_db
from app.errors import not_found
from app.schemas.common import MonitorId
from app.security.auth import Principal, require
from app.services.ecg import synth_ecg

router = APIRouter(tags=["ward"])

_SEVERITY_ORDER = "case a.severity when 'critical' then 0 when 'warning' then 1 else 2 end"

WARD_SQL = f"""
select b.id as bed_id, b.label, b.room, b.pos_x, b.pos_z,
       p.id as patient_id, p.first_name, p.last_name, p.acuity, p.mrn, p.date_of_birth, p.code_status,
       m.id as monitor_id, m.status as monitor_status, m.battery_pct, m.connection, m.sensor_status, m.scenario,
       m.last_seen_at,
       v.heart_rate, v.spo2, v.resp_rate, v.systolic, v.diastolic, v.recorded_at, v.quality,
       (select count(*) from public.alarms a where a.monitor_id = m.id and a.state = 'active') as active_alarms,
       (select count(*) from public.alarms a where a.monitor_id = m.id and a.state = 'active'
          and a.acknowledged_at is null) as unacknowledged,
       (select a.severity from public.alarms a where a.monitor_id = m.id and a.state = 'active'
          order by {_SEVERITY_ORDER} limit 1) as top_severity,
       (select json_agg(json_build_object('id', a.id, 'type', a.type, 'severity', a.severity, 'message', a.message,
                 'acknowledged', a.acknowledged_at is not null, 'category', a.category) order by {_SEVERITY_ORDER})
          from public.alarms a where a.monitor_id = m.id and a.state = 'active') as alarms
from public.beds b
left join public.patients p on p.bed_id = b.id and p.status = 'admitted'
left join public.monitors m on m.bed_id = b.id
left join lateral (
  select heart_rate, spo2, resp_rate, systolic, diastolic, recorded_at, quality
  from public.vital_readings r where r.monitor_id = m.id and r.patient_id = p.id
  order by r.recorded_at desc limit 1) v on true
order by b.id
"""

_CLINICAL_FIELDS = ("patient_id", "first_name", "last_name", "acuity", "mrn", "date_of_birth", "code_status",
                    "heart_rate", "spo2", "resp_rate", "systolic", "diastolic", "recorded_at", "quality")


def ward_rows(conn: psycopg.Connection, principal: Principal) -> list[dict]:
    rows = conn.execute(WARD_SQL).fetchall()
    out = []
    for row in rows:
        item = dict(row)
        item["battery_pct"] = float(item["battery_pct"]) if item["battery_pct"] is not None else None
        item["occupied"] = item["patient_id"] is not None
        if not principal.can("vitals:view"):
            # Data minimisation: technical roles see device state, not identities or vital signs.
            for field in _CLINICAL_FIELDS:
                item[field] = None
        out.append(item)
    return out


@router.get("/ward/overview")
def overview(principal: Principal = Depends(require("ward:view")), conn: psycopg.Connection = Depends(get_db)) -> dict:
    beds = ward_rows(conn, principal)
    kpi = conn.execute(
        """select
             (select count(*) from public.patients where status = 'admitted') as patients,
             (select count(*) from public.monitors m join public.patients p on p.bed_id = m.bed_id
                where m.status = 'active' and m.connection = 'online') as monitored,
             (select count(*) from public.alarms where state = 'active' and severity = 'critical') as critical,
             (select count(*) from public.alarms where state = 'active' and severity <> 'critical') as warnings,
             (select count(*) from public.alarms where state = 'active' and acknowledged_at is null) as unacknowledged,
             (select count(*) from public.monitors where connection = 'offline' and status = 'active') as offline,
             (select count(*) from public.monitors where battery_pct < 20 and status = 'active') as low_battery,
             (select count(*) from public.monitors where next_maintenance_due < current_date
                and status <> 'retired') as maintenance_due,
             (select count(*) from public.maintenance_records where status <> 'completed') as open_tickets"""
    ).fetchone()
    sim = conn.execute("select tick, sim_time, tick_seconds, last_advanced_at from public.sim_state where id = 1").fetchone()
    return {"kpis": kpi, "beds": beds, "simulation": sim}


@router.get("/monitors/{monitor_id}/ecg")
def ecg(monitor_id: MonitorId, seconds: int = Query(default=6, ge=2, le=12),
        principal: Principal = Depends(require("vitals:view")), conn: psycopg.Connection = Depends(get_db)) -> dict:
    m = conn.execute(
        """select m.id, m.connection, m.sensor_status, m.status, s.seed, s.tick,
                  (select heart_rate from public.vital_readings v where v.monitor_id = m.id
                     order by recorded_at desc limit 1) as heart_rate
           from public.monitors m cross join public.sim_state s where m.id = %s and s.id = 1""",
        (monitor_id,),
    ).fetchone()
    if m is None:
        raise not_found("Monitor")
    fs = 125
    if m["connection"] == "offline" or m["status"] != "active":
        return {"monitor_id": monitor_id, "fs": fs, "status": "no_signal", "samples": [], "heart_rate": None}
    leads_off = m["sensor_status"] == "ecg_leads_off"
    samples = synth_ecg(m["heart_rate"], seconds=seconds, fs=fs, seed=zlib.crc32(f"{m['seed']}:{m['tick']}:{monitor_id}".encode()),
                        leads_off=leads_off, artifact=m["sensor_status"] == "spo2_probe_off")
    return {"monitor_id": monitor_id, "fs": fs, "status": "leads_off" if leads_off else "ok",
            "samples": samples, "heart_rate": None if leads_off else m["heart_rate"], "tick": m["tick"]}
