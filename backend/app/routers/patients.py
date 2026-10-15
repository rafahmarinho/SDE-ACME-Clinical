"""Patients: search, details, vitals history, notes, per-patient thresholds and emergency access."""

from datetime import timedelta
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Query
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError, not_found
from app.routers._shared import ensure_patient_access, has_emergency_access, page_params, staff_name
from app.schemas.requests import EmergencyAccessIn, NoteIn, PatientSearchIn, PatientUpdateIn, RestrictionIn, ThresholdSetIn
from app.security.auth import Principal, get_principal, require
from app.security.context import RequestContext, get_context
from app.security.crypto import decrypt_text, encrypt_text
from app.services import audit, simulation

router = APIRouter(prefix="/patients", tags=["patients"])

_SORTS = {
    "bed": "p.bed_id nulls last, p.last_name",
    "name": "p.last_name, p.first_name",
    "acuity": "case p.acuity when 'high' then 0 when 'medium' then 1 else 2 end, p.bed_id nulls last",
    "admitted": "p.admitted_at desc",
}


@router.post("/search")
def search(body: PatientSearchIn, principal: Principal = Depends(require("patients:view")),
           conn: psycopg.Connection = Depends(get_db)) -> dict:
    """POST so that names typed in the search box never end up in URLs or access logs."""
    where = ["true"]
    params: dict = {}
    if body.q:
        where.append("(p.first_name ilike %(q)s or p.last_name ilike %(q)s or p.mrn ilike %(q)s or p.bed_id ilike %(q)s"
                     " or (p.first_name || ' ' || p.last_name) ilike %(q)s)")
        escaped = body.q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params["q"] = f"%{escaped}%"
    if body.status != "all":
        where.append("p.status = %(status)s")
        params["status"] = body.status
    if body.acuity != "all":
        where.append("p.acuity = %(acuity)s")
        params["acuity"] = body.acuity
    if body.alarm == "active":
        where.append("exists (select 1 from public.alarms a where a.patient_id = p.id and a.state = 'active')")
    elif body.alarm == "none":
        where.append("not exists (select 1 from public.alarms a where a.patient_id = p.id and a.state = 'active')")
    if body.monitored == "yes":
        where.append("m.id is not null")
    elif body.monitored == "no":
        where.append("m.id is null")
    limit, offset = page_params(body.page, body.page_size)
    params.update({"limit": limit, "offset": offset})
    # Only fixed SQL fragments are concatenated; every value is a bound parameter.
    where_sql = " and ".join(where)
    joins = "from public.patients p left join public.monitors m on m.bed_id = p.bed_id"
    total = conn.execute(f"select count(*) as n {joins} where {where_sql}", params).fetchone()["n"]
    rows = conn.execute(
        f"""select p.id, p.mrn, p.first_name, p.last_name, p.date_of_birth, p.sex, p.bed_id, p.status, p.acuity,
                   p.diagnosis, p.attending_physician, p.admitted_at, p.restricted, m.id as monitor_id,
                   m.connection,
                   (select count(*) from public.alarms a where a.patient_id = p.id and a.state = 'active') as active_alarms,
                   (select a.severity from public.alarms a where a.patient_id = p.id and a.state = 'active'
                      order by case a.severity when 'critical' then 0 when 'warning' then 1 else 2 end limit 1) as top_severity,
                   v.heart_rate, v.spo2, v.resp_rate, v.systolic, v.diastolic
            {joins}
            left join lateral (select heart_rate, spo2, resp_rate, systolic, diastolic from public.vital_readings r
                               where r.patient_id = p.id order by r.recorded_at desc limit 1) v on true
            where {where_sql}
            order by {_SORTS[body.sort]} limit %(limit)s offset %(offset)s""",
        params,
    ).fetchall()
    return {"items": rows, "total": total, "page": body.page, "page_size": limit}


@router.get("/{patient_id}")
def detail(patient_id: UUID, principal: Principal = Depends(get_principal), conn: psycopg.Connection = Depends(get_db),
           ctx: RequestContext = Depends(get_context)) -> dict:
    ensure_patient_access(conn, principal, patient_id, "patients:view", ctx)
    p = conn.execute(
        """select p.id, p.mrn, p.first_name, p.last_name, p.date_of_birth, p.sex, p.bed_id, p.status, p.admitted_at,
                  p.diagnosis, p.attending_physician, p.acuity, p.allergies, p.code_status, p.restricted,
                  b.label as bed_label, b.room, m.id as monitor_id, m.model as monitor_model, m.connection,
                  m.sensor_status, m.battery_pct, m.last_seen_at
           from public.patients p left join public.beds b on b.id = p.bed_id
           left join public.monitors m on m.bed_id = p.bed_id where p.id = %s""",
        (patient_id,),
    ).fetchone()
    latest = conn.execute(
        """select heart_rate, spo2, resp_rate, systolic, diastolic, recorded_at, quality from public.vital_readings
           where patient_id = %s order by recorded_at desc limit 1""",
        (patient_id,),
    ).fetchone()
    alarms = conn.execute(
        """select id, type, category, severity, message, state, raised_at, acknowledged_at, acknowledged_by_name, ack_note
           from public.alarms where patient_id = %s and (state = 'active' or raised_at > now() - interval '24 hours')
           order by state, raised_at desc limit 50""",
        (patient_id,),
    ).fetchall()
    defaults, overrides = simulation.load_thresholds(conn)
    emergency = None
    if not principal.can("patients:view"):
        emergency = conn.execute(
            """select expires_at, reason from public.emergency_access where user_id = %s and patient_id = %s
               and expires_at > now() order by expires_at desc limit 1""",
            (principal.id, patient_id),
        ).fetchone()
    audit.record(conn, "patient.view", actor=principal, entity_type="patient", entity_id=str(patient_id), ctx=ctx)
    return {
        **p, "battery_pct": float(p["battery_pct"]) if p["battery_pct"] is not None else None,
        "latest": latest, "alarms": alarms,
        "thresholds": simulation.effective_thresholds(defaults, overrides, patient_id),
        "emergency_access": emergency,
    }


@router.patch("/{patient_id}")
def update(patient_id: UUID, body: PatientUpdateIn, principal: Principal = Depends(require("patients:edit")),
           conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    row = conn.execute(
        """update public.patients set diagnosis = %s, attending_physician = %s, acuity = %s, allergies = %s,
               code_status = %s, updated_at = now() where id = %s returning id""",
        (body.diagnosis, body.attending_physician, body.acuity, body.allergies, body.code_status, patient_id),
    ).fetchone()
    if row is None:
        raise not_found("Patient")
    audit.record(conn, "patient.update", actor=principal, entity_type="patient", entity_id=str(patient_id),
                 details={"fields": sorted(body.model_dump().keys())}, ctx=ctx)
    return {"ok": True}


@router.put("/{patient_id}/restriction")
def set_restriction(patient_id: UUID, body: RestrictionIn, principal: Principal = Depends(require("patients:restrict")),
                    conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    row = conn.execute("update public.patients set restricted = %s, updated_at = now() where id = %s returning id",
                       (body.restricted, patient_id)).fetchone()
    if row is None:
        raise not_found("Patient")
    audit.record(conn, "patient.restriction", actor=principal, entity_type="patient", entity_id=str(patient_id),
                 details={"restricted": body.restricted}, ctx=ctx)
    return {"restricted": body.restricted}


@router.get("/{patient_id}/vitals")
def vitals(patient_id: UUID, minutes: int = Query(default=30, ge=5, le=1440), principal: Principal = Depends(get_principal),
           conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    ensure_patient_access(conn, principal, patient_id, "vitals:view", ctx)
    end = conn.execute(
        "select max(recorded_at) as t from public.vital_readings where patient_id = %s", (patient_id,)
    ).fetchone()["t"]
    if end is None:
        return {"items": []}
    rows = conn.execute(
        """select recorded_at, heart_rate, spo2, resp_rate, systolic, diastolic, quality from public.vital_readings
           where patient_id = %s and recorded_at >= %s order by recorded_at limit 2000""",
        (patient_id, end - timedelta(minutes=minutes)),
    ).fetchall()
    return {"items": rows}


@router.get("/{patient_id}/notes")
def list_notes(patient_id: UUID, principal: Principal = Depends(get_principal), conn: psycopg.Connection = Depends(get_db),
               ctx: RequestContext = Depends(get_context)) -> dict:
    ensure_patient_access(conn, principal, patient_id, "notes:view", ctx)
    rows = conn.execute(
        """select n.id, n.category, n.body_encrypted, n.created_at, n.author_id, pr.full_name, pr.role,
                  pr.anonymized_at
           from public.notes n left join public.profiles pr on pr.id = n.author_id
           where n.patient_id = %s order by n.created_at desc limit 200""",
        (patient_id,),
    ).fetchall()
    items = []
    for r in rows:
        try:
            body = decrypt_text(r["body_encrypted"], f"note:{r['id']}")
        except Exception:  # noqa: BLE001 - never leak crypto errors; flag the record instead
            body = "[This note could not be decrypted]"
        items.append({"id": r["id"], "category": r["category"], "body": body, "created_at": r["created_at"],
                      "author": staff_name(r["full_name"], r["anonymized_at"]), "author_role": r["role"]})
    return {"items": items}


@router.post("/{patient_id}/notes", status_code=201)
def add_note(patient_id: UUID, body: NoteIn, principal: Principal = Depends(require("notes:create")),
             conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    patient = conn.execute("select id, status from public.patients where id = %s", (patient_id,)).fetchone()
    if patient is None:
        raise not_found("Patient")
    if body.category == "physician" and principal.role != "physician":
        raise ApiError(403, "forbidden", "Only physicians can write physician notes.")
    row = conn.execute(
        """insert into public.notes (patient_id, author_id, category, body_encrypted)
           values (%s, %s, %s, 'pending') returning id, created_at""",
        (patient_id, principal.id, body.category),
    ).fetchone()
    conn.execute("update public.notes set body_encrypted = %s where id = %s",
                 (encrypt_text(body.body, f"note:{row['id']}"), row["id"]))
    audit.record(conn, "note.create", actor=principal, entity_type="patient", entity_id=str(patient_id),
                 details={"note_id": str(row["id"]), "category": body.category}, ctx=ctx)
    return {"id": row["id"], "category": body.category, "body": body.body, "created_at": row["created_at"],
            "author": principal.full_name, "author_role": principal.role}


@router.put("/{patient_id}/thresholds")
def set_thresholds(patient_id: UUID, body: ThresholdSetIn, principal: Principal = Depends(require("thresholds:edit_patient")),
                   conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    if conn.execute("select 1 from public.patients where id = %s", (patient_id,)).fetchone() is None:
        raise not_found("Patient")
    for item in body.items:
        if item.parameter in body.reset_to_default:
            continue
        conn.execute(
            """insert into public.thresholds (patient_id, parameter, low, high, enabled, updated_by, updated_at)
               values (%s, %s, %s, %s, %s, %s, now())
               on conflict (coalesce(patient_id, '00000000-0000-0000-0000-000000000000'::uuid), parameter)
               do update set low = excluded.low, high = excluded.high, enabled = excluded.enabled,
                             updated_by = excluded.updated_by, updated_at = now()""",
            (patient_id, item.parameter, item.low, item.high, item.enabled, principal.id),
        )
    for parameter in body.reset_to_default:
        conn.execute("delete from public.thresholds where patient_id = %s and parameter = %s", (patient_id, parameter))
    audit.record(conn, "thresholds.patient_update", actor=principal, entity_type="patient", entity_id=str(patient_id),
                 details={"items": [i.model_dump() for i in body.items], "reset": body.reset_to_default}, ctx=ctx)
    simulation.log_event(conn, "thresholds", "Alarm limits changed for a patient", patient_id=patient_id,
                         actor_id=principal.id, data={"parameters": [i.parameter for i in body.items]})
    defaults, overrides = simulation.load_thresholds(conn)
    return {"thresholds": simulation.effective_thresholds(defaults, overrides, patient_id)}


@router.post("/{patient_id}/emergency-access", status_code=201)
def emergency_access(patient_id: UUID, body: EmergencyAccessIn, principal: Principal = Depends(require("emergency:request")),
                     conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    """Break-glass: time-limited access to one patient's chart, justified, audited and reported."""
    if conn.execute("select 1 from public.patients where id = %s", (patient_id,)).fetchone() is None:
        raise not_found("Patient")
    if has_emergency_access(conn, principal.id, patient_id):
        raise ApiError(409, "conflict", "You already have emergency access to this patient.")
    minutes = get_settings().emergency_access_minutes
    row = conn.execute(
        """insert into public.emergency_access (user_id, patient_id, reason, expires_at)
           values (%s, %s, %s, now() + make_interval(mins => %s)) returning id, expires_at""",
        (principal.id, patient_id, body.reason, minutes),
    ).fetchone()
    conn.execute(
        """insert into public.integration_outbox (channel, recipient, subject, payload)
           values ('privacy_office', 'privacy-office', 'Emergency access granted', %s)""",
        (Jsonb({"user": principal.email, "patient_id": str(patient_id), "expires_at": row["expires_at"].isoformat()}),),
    )
    audit.record(conn, "patient.emergency_access", actor=principal, entity_type="patient", entity_id=str(patient_id),
                 details={"grant_id": str(row["id"]), "minutes": minutes}, ctx=ctx)
    return {"id": row["id"], "expires_at": row["expires_at"]}
