"""Administration: audit trail, integrity verification, emergency-access review, security configuration."""

from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Query

from app.config import get_settings
from app.db import get_db
from app.errors import not_found
from app.routers._shared import page_params
from app.schemas.common import OptionalShortText
from app.security import passwords
from app.security.auth import Principal, require
from app.security.context import RequestContext, get_context
from app.services import audit

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/audit")
def audit_log(
    q: OptionalShortText = "",
    outcome: Literal["success", "failure", "denied", "all"] = "all",
    page: int = Query(default=1, ge=1, le=1000),
    page_size: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(require("audit:view")),
    conn: psycopg.Connection = Depends(get_db),
) -> dict:
    where = ["true"]
    params: dict = {}
    if q:
        where.append("(a.action ilike %(q)s or a.actor_email ilike %(q)s or a.entity_id ilike %(q)s)")
        params["q"] = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    if outcome != "all":
        where.append("a.outcome = %(outcome)s")
        params["outcome"] = outcome
    limit, offset = page_params(page, page_size)
    params.update({"limit": limit, "offset": offset})
    where_sql = " and ".join(where)
    total = conn.execute(f"select count(*) as n from public.audit_log a where {where_sql}", params).fetchone()["n"]
    rows = conn.execute(
        f"""select a.id, a.created_at, a.actor_email, a.actor_role, a.action, a.entity_type, a.entity_id, a.outcome,
                   a.details, a.ip, a.request_id
            from public.audit_log a where {where_sql} order by a.id desc limit %(limit)s offset %(offset)s""",
        params,
    ).fetchall()
    return {"items": rows, "total": total, "page": page, "page_size": limit}


@router.get("/audit/verify")
def verify(principal: Principal = Depends(require("audit:view")), conn: psycopg.Connection = Depends(get_db)) -> dict:
    return audit.verify_chain(conn)


@router.get("/emergency-access")
def emergency_access(principal: Principal = Depends(require("audit:view")), conn: psycopg.Connection = Depends(get_db)) -> dict:
    rows = conn.execute(
        """select e.id, e.reason, e.granted_at, e.expires_at, e.reviewed_at, u.full_name as user_name, u.role,
                  p.first_name || ' ' || p.last_name as patient_name, p.bed_id
           from public.emergency_access e join public.profiles u on u.id = e.user_id
           join public.patients p on p.id = e.patient_id order by e.granted_at desc limit 100"""
    ).fetchall()
    return {"items": rows}


@router.post("/emergency-access/{grant_id}/review")
def review_emergency(grant_id: UUID, principal: Principal = Depends(require("audit:view")),
                     conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    row = conn.execute(
        "update public.emergency_access set reviewed_by = %s, reviewed_at = now() where id = %s returning id",
        (principal.id, grant_id),
    ).fetchone()
    if row is None:
        raise not_found("Emergency access grant")
    audit.record(conn, "emergency_access.review", actor=principal, entity_type="emergency_access",
                 entity_id=str(grant_id), ctx=ctx)
    return {"ok": True}


@router.get("/security-settings")
def security_settings(principal: Principal = Depends(require("team:manage"))) -> dict:
    """Read-only view of the effective security configuration (managed through environment variables)."""
    s = get_settings()
    return {
        "password_policy": passwords.policy(),
        "lockout": {"max_failures": s.login_max_failures, "lockout_minutes": s.lockout_minutes},
        "sessions": {"idle_timeout_minutes": s.idle_timeout_minutes, "absolute_timeout_hours": s.absolute_timeout_hours,
                     "max_concurrent_sessions": s.max_concurrent_sessions},
        "mfa": {"required_for_admin_actions": s.require_admin_mfa},
        "emergency_access_minutes": s.emergency_access_minutes,
        "data_retention_days": s.data_retention_days,
        "uploads": {"max_bytes": s.max_upload_bytes, "types": ["image/png", "image/jpeg", "image/webp"]},
        "cors_origins": s.origins,
        "environment": s.environment,
    }
