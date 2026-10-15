"""Helpers shared by the clinical routers."""

from typing import Any
from uuid import UUID

import psycopg

from app.errors import forbidden, not_found
from app.security.auth import Principal
from app.security.context import RequestContext
from app.services import audit

BREAK_GLASS_PERMISSIONS = {"patients:view", "vitals:view", "notes:view"}


def has_emergency_access(conn: psycopg.Connection, user_id: UUID, patient_id: Any) -> bool:
    return conn.execute(
        "select 1 from public.emergency_access where user_id = %s and patient_id = %s and expires_at > now()",
        (user_id, patient_id),
    ).fetchone() is not None


def ensure_patient_access(conn: psycopg.Connection, principal: Principal, patient_id: UUID, permission: str,
                          ctx: RequestContext) -> dict:
    """Object-level check: the patient must exist and the caller must hold the permission
    (or an unexpired emergency 'break-glass' grant for this specific patient)."""
    patient = conn.execute("select id, status, restricted from public.patients where id = %s", (patient_id,)).fetchone()
    if patient is None:
        raise not_found("Patient")
    if principal.can(permission):
        return patient
    if permission in BREAK_GLASS_PERMISSIONS and has_emergency_access(conn, principal.id, patient_id):
        audit.record(conn, "patient.emergency_read", actor=principal, entity_type="patient", entity_id=str(patient_id),
                     details={"permission": permission}, ctx=ctx)
        return patient
    audit.record(conn, "authz.denied", actor=principal, outcome="denied", entity_type="patient",
                 entity_id=str(patient_id), details={"permission": permission}, ctx=ctx)
    raise forbidden()


def staff_name(name: str | None, anonymized: Any = None) -> str:
    if anonymized:
        return "Former staff member"
    return name or "System"


def page_params(page: int, page_size: int) -> tuple[int, int]:
    page = max(1, min(page, 1000))
    page_size = max(1, min(page_size, 100))
    return page_size, (page - 1) * page_size
