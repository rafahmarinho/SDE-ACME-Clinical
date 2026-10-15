"""Reading ingestion for external (emulated) bedside monitors.

Devices authenticate every request with HMAC-SHA256 over "timestamp.nonce.body" using a per-device
secret derived from DEVICE_MASTER_KEY. Requests older than 5 minutes or re-using a nonce are rejected.
"""

import re
from datetime import UTC, datetime

import psycopg
from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError, conflict, unauthorized
from app.schemas.requests import DeviceReadingIn
from app.security import ratelimit
from app.security.context import RequestContext, get_context
from app.security.crypto import constant_time_equals, sign_device_payload
from app.services import audit, simulation

router = APIRouter(prefix="/devices", tags=["device-ingest"])

_MONITOR = re.compile(r"^MON-\d{2}$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


@router.post("/ingest", status_code=202)
async def ingest(request: Request, conn: psycopg.Connection = Depends(get_db),
                 ctx: RequestContext = Depends(get_context)) -> dict:
    monitor_id = request.headers.get("x-device-id", "")
    timestamp = request.headers.get("x-timestamp", "")
    nonce = request.headers.get("x-nonce", "")
    signature = request.headers.get("x-signature", "")
    if not (_MONITOR.match(monitor_id) and timestamp.isdigit() and _NONCE.match(nonce) and len(signature) == 64):
        raise unauthorized("device_auth_failed", "Device authentication failed.")
    ratelimit.hit(conn, f"ingest:{monitor_id}", limit=120, window_seconds=60)
    body = await request.body()
    if abs(datetime.now(UTC).timestamp() - int(timestamp)) > 300:
        raise unauthorized("device_auth_failed", "Device authentication failed.")
    expected = sign_device_payload(monitor_id, timestamp, nonce, body)
    if not constant_time_equals(expected, signature.lower()):
        audit.record(conn, "device.auth_failed", actor_email=monitor_id, outcome="failure", ctx=ctx)
        raise unauthorized("device_auth_failed", "Device authentication failed.")
    inserted = conn.execute(
        "insert into public.device_nonces (nonce, monitor_id) values (%s, %s) on conflict do nothing returning nonce",
        (nonce, monitor_id),
    ).fetchone()
    if inserted is None:
        raise conflict("Replayed request.")
    try:
        reading = DeviceReadingIn.model_validate_json(body)
    except ValidationError as exc:
        raise ApiError(422, "validation_error", "The reading is not valid.") from exc

    m = conn.execute(
        """select m.id, m.bed_id, m.status, p.id as patient_id, s.tick, s.sim_time
           from public.monitors m cross join public.sim_state s
           left join public.patients p on p.bed_id = m.bed_id and p.status = 'admitted'
           where m.id = %s and s.id = 1""",
        (monitor_id,),
    ).fetchone()
    if m is None or m["status"] != "active" or m["patient_id"] is None:
        raise conflict("This monitor is not active on an occupied bed.")
    now = max(datetime.now(UTC), m["sim_time"])
    conn.execute(
        """insert into public.vital_readings (monitor_id, patient_id, bed_id, tick, recorded_at, heart_rate, spo2,
               resp_rate, systolic, diastolic, battery_pct, quality, source)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'device')""",
        (monitor_id, m["patient_id"], m["bed_id"], m["tick"], now, reading.heart_rate, reading.spo2, reading.resp_rate,
         reading.systolic, reading.diastolic, reading.battery_pct, reading.quality),
    )
    conn.execute(
        """update public.monitors set connection = 'online', last_seen_at = %s,
               battery_pct = coalesce(%s, battery_pct), updated_at = now() where id = %s""",
        (now, reading.battery_pct, monitor_id),
    )
    simulation.log_event(conn, "integration", f"Signed reading received from {monitor_id}", monitor_id=monitor_id,
                         data={"source": "device"})
    return {"accepted": True, "max_skew_seconds": 300, "environment": get_settings().environment}
