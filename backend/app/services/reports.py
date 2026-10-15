"""Report generation (Python). Produces a JSON summary for the UI and a CSV file for download.

* CSV cells that could be interpreted as spreadsheet formulas are neutralised.
* De-identified reports replace names and record numbers with keyed pseudonyms, convert dates of
  birth to age bands and exclude patients whose data processing is restricted.
"""

import csv
import io
import statistics
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg

from app.security.crypto import pseudonym

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")

TITLES = {
    "shift_summary": "Shift summary",
    "alarm_log": "Alarm log",
    "device_maintenance": "Device and maintenance status",
    "patient_vitals": "Patient vitals trend",
}


def csv_safe(value: Any) -> Any:
    if isinstance(value, str) and value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def to_csv(columns: list[str], rows: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow([csv_safe("" if row.get(c) is None else row.get(c)) for c in columns])
    return buf.getvalue().encode("utf-8-sig")


def _age_band(dob: date, today: date) -> str:
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    low = age // 10 * 10
    return f"{low}-{low + 9}"


def _patient_label(p: dict, deid: bool) -> dict[str, Any]:
    if deid:
        return {"patient": pseudonym("patient", str(p["patient_id"])), "mrn": pseudonym("mrn", p["mrn"])}
    return {"patient": f"{p['last_name']}, {p['first_name']}", "mrn": p["mrn"]}


def _now(conn: psycopg.Connection) -> datetime:
    row = conn.execute("select sim_time from public.sim_state where id = 1").fetchone()
    return max(row["sim_time"], datetime.now(UTC)) if row else datetime.now(UTC)


def _fmt(ts: datetime | None) -> str | None:
    return ts.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC") if ts else None


def shift_summary(conn: psycopg.Connection, hours: int, deid: bool) -> tuple[list[str], list[dict], dict]:
    end = _now(conn)
    start = end - timedelta(hours=hours)
    rows: list[dict] = []
    patients = conn.execute(
        """select p.id as patient_id, p.mrn, p.first_name, p.last_name, p.date_of_birth, p.bed_id, p.acuity,
                  p.restricted,
                  (select count(*) from public.vital_readings v where v.patient_id = p.id and v.recorded_at >= %(s)s) as n,
                  (select min(heart_rate) from public.vital_readings v where v.patient_id = p.id and v.recorded_at >= %(s)s) as hr_min,
                  (select max(heart_rate) from public.vital_readings v where v.patient_id = p.id and v.recorded_at >= %(s)s) as hr_max,
                  (select min(spo2) from public.vital_readings v where v.patient_id = p.id and v.recorded_at >= %(s)s) as spo2_min,
                  (select max(resp_rate) from public.vital_readings v where v.patient_id = p.id and v.recorded_at >= %(s)s) as rr_max,
                  (select count(*) from public.alarms a where a.patient_id = p.id and a.raised_at >= %(s)s) as alarms,
                  (select count(*) from public.alarms a where a.patient_id = p.id and a.raised_at >= %(s)s
                      and a.severity = 'critical') as critical,
                  (select count(*) from public.alarms a where a.patient_id = p.id and a.state = 'active') as active_alarms
           from public.patients p where p.status = 'admitted' order by p.bed_id nulls last""",
        {"s": start},
    ).fetchall()
    for p in patients:
        if deid and p["restricted"]:
            continue
        latest = conn.execute(
            """select heart_rate, spo2, resp_rate, systolic, diastolic, recorded_at from public.vital_readings
               where patient_id = %s order by recorded_at desc limit 1""",
            (p["patient_id"],),
        ).fetchone() or {}
        rows.append({
            "bed": p["bed_id"], **_patient_label(p, deid), "acuity": p["acuity"],
            "age_band": _age_band(p["date_of_birth"], end.date()) if deid else None,
            "readings": p["n"], "hr_latest": latest.get("heart_rate"), "hr_min": p["hr_min"], "hr_max": p["hr_max"],
            "spo2_latest": latest.get("spo2"), "spo2_min": p["spo2_min"], "rr_latest": latest.get("resp_rate"),
            "rr_max": p["rr_max"],
            "bp_latest": f"{latest['systolic']}/{latest['diastolic']}" if latest.get("systolic") else None,
            "alarms": p["alarms"], "critical_alarms": p["critical"], "active_alarms": p["active_alarms"],
        })
    columns = ["bed", "patient", "mrn"] + (["age_band"] if deid else []) + [
        "acuity", "readings", "hr_latest", "hr_min", "hr_max", "spo2_latest", "spo2_min", "rr_latest", "rr_max",
        "bp_latest", "alarms", "critical_alarms", "active_alarms"]
    summary = {
        "period_start": _fmt(start), "period_end": _fmt(end), "patients": len(rows),
        "alarms": sum(r["alarms"] for r in rows), "critical_alarms": sum(r["critical_alarms"] for r in rows),
        "active_alarms": sum(r["active_alarms"] for r in rows),
        "lowest_spo2": min((r["spo2_min"] for r in rows if r["spo2_min"] is not None), default=None),
    }
    return columns, rows, summary


def alarm_log(conn: psycopg.Connection, hours: int, deid: bool) -> tuple[list[str], list[dict], dict]:
    end = _now(conn)
    start = end - timedelta(hours=hours)
    alarms = conn.execute(
        """select a.*, p.id as pid, p.mrn, p.first_name, p.last_name, p.restricted
           from public.alarms a left join public.patients p on p.id = a.patient_id
           where a.raised_at >= %s order by a.raised_at desc limit 5000""",
        (start,),
    ).fetchall()
    rows: list[dict] = []
    response: list[float] = []
    for a in alarms:
        if deid and a["restricted"]:
            continue
        label = (_patient_label({"patient_id": a["pid"], "mrn": a["mrn"], "first_name": a["first_name"],
                                 "last_name": a["last_name"]}, deid) if a["pid"] else {"patient": None, "mrn": None})
        seconds = None
        if a["acknowledged_at"]:
            seconds = max(0, round((a["acknowledged_at"] - a["raised_at"]).total_seconds()))
            response.append(seconds)
        rows.append({
            "raised_at": _fmt(a["raised_at"]), "bed": a["bed_id"], "monitor": a["monitor_id"], **label,
            "type": a["type"], "category": a["category"], "severity": a["severity"], "message": a["message"],
            "state": a["state"], "acknowledged_at": _fmt(a["acknowledged_at"]),
            "acknowledged_by": None if deid else a["acknowledged_by_name"], "response_seconds": seconds,
            "resolved_at": _fmt(a["resolved_at"]),
        })
    columns = ["raised_at", "bed", "monitor", "patient", "mrn", "type", "category", "severity", "message", "state",
               "acknowledged_at", "acknowledged_by", "response_seconds", "resolved_at"]
    summary = {
        "period_start": _fmt(start), "period_end": _fmt(end), "alarms": len(rows),
        "critical": sum(1 for r in rows if r["severity"] == "critical"),
        "technical": sum(1 for r in rows if r["category"] == "technical"),
        "unacknowledged": sum(1 for r in rows if r["acknowledged_at"] is None),
        "median_response_seconds": statistics.median(response) if response else None,
    }
    return columns, rows, summary


def device_maintenance(conn: psycopg.Connection, hours: int, deid: bool) -> tuple[list[str], list[dict], dict]:
    today = datetime.now(UTC).date()
    monitors = conn.execute(
        """select m.id, m.serial_number, m.model, m.firmware, m.bed_id, m.status, m.battery_pct, m.connection,
                  m.sensor_status, m.last_maintenance_at, m.next_maintenance_due,
                  (select count(*) from public.maintenance_records r where r.monitor_id = m.id and r.status <> 'completed') as open_tickets,
                  (select count(*) from public.alarms a where a.monitor_id = m.id and a.category = 'technical'
                      and a.state = 'active') as technical_alarms
           from public.monitors m order by m.id"""
    ).fetchall()
    rows = [{
        "monitor": m["id"], "serial": m["serial_number"], "model": m["model"], "firmware": m["firmware"],
        "bed": m["bed_id"], "status": m["status"], "battery_pct": float(m["battery_pct"]), "connection": m["connection"],
        "sensor": m["sensor_status"], "last_maintenance": _fmt(m["last_maintenance_at"]),
        "next_due": m["next_maintenance_due"].isoformat() if m["next_maintenance_due"] else None,
        "overdue": bool(m["next_maintenance_due"] and m["next_maintenance_due"] < today),
        "open_tickets": m["open_tickets"], "technical_alarms": m["technical_alarms"],
    } for m in monitors]
    columns = ["monitor", "serial", "model", "firmware", "bed", "status", "battery_pct", "connection", "sensor",
               "last_maintenance", "next_due", "overdue", "open_tickets", "technical_alarms"]
    summary = {
        "monitors": len(rows), "assigned": sum(1 for r in rows if r["bed"]),
        "offline": sum(1 for r in rows if r["connection"] == "offline"),
        "low_battery": sum(1 for r in rows if r["battery_pct"] < 20),
        "overdue": sum(1 for r in rows if r["overdue"]), "open_tickets": sum(r["open_tickets"] for r in rows),
    }
    return columns, rows, summary


def patient_vitals(conn: psycopg.Connection, hours: int, deid: bool, patient_id: Any) -> tuple[list[str], list[dict], dict]:
    end = _now(conn)
    start = end - timedelta(hours=hours)
    p = conn.execute("select id as patient_id, mrn, first_name, last_name, restricted from public.patients where id = %s",
                     (patient_id,)).fetchone()
    if p is None:
        raise LookupError("patient")
    if deid and p["restricted"]:
        raise PermissionError("restricted")
    readings = conn.execute(
        """select recorded_at, heart_rate, spo2, resp_rate, systolic, diastolic, quality, monitor_id
           from public.vital_readings where patient_id = %s and recorded_at >= %s order by recorded_at limit 20000""",
        (patient_id, start),
    ).fetchall()
    label = _patient_label(p, deid)
    rows = [{"recorded_at": _fmt(r["recorded_at"]), **label, "monitor": r["monitor_id"], "heart_rate": r["heart_rate"],
             "spo2": r["spo2"], "resp_rate": r["resp_rate"], "systolic": r["systolic"], "diastolic": r["diastolic"],
             "quality": r["quality"]} for r in readings]

    def stats(field: str) -> dict[str, Any]:
        values = [r[field] for r in readings if r[field] is not None]
        if not values:
            return {"min": None, "max": None, "avg": None}
        return {"min": min(values), "max": max(values), "avg": round(sum(values) / len(values), 1)}

    columns = ["recorded_at", "patient", "mrn", "monitor", "heart_rate", "spo2", "resp_rate", "systolic", "diastolic",
               "quality"]
    summary = {"period_start": _fmt(start), "period_end": _fmt(end), "patient": label["patient"],
               "readings": len(rows), **{f: stats(f) for f in ("heart_rate", "spo2", "resp_rate", "systolic")}}
    return columns, rows, summary


def build(conn: psycopg.Connection, kind: str, hours: int, deid: bool, patient_id: Any = None
          ) -> tuple[str, bytes, dict, int]:
    if kind == "shift_summary":
        columns, rows, summary = shift_summary(conn, hours, deid)
    elif kind == "alarm_log":
        columns, rows, summary = alarm_log(conn, hours, deid)
    elif kind == "device_maintenance":
        columns, rows, summary = device_maintenance(conn, hours, deid)
    elif kind == "patient_vitals":
        columns, rows, summary = patient_vitals(conn, hours, deid, patient_id)
    else:
        raise ValueError("unknown report kind")
    preview = rows[:50]
    summary = {**summary, "columns": columns, "preview": preview}
    title = TITLES[kind] + (" (de-identified)" if deid else "")
    if kind == "patient_vitals":
        title = f"{TITLES[kind]} - {summary['patient']}" + (" (de-identified)" if deid else "")
    return title, to_csv(columns, rows), summary, len(rows)
