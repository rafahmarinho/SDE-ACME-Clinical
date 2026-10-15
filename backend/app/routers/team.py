"""Team management (administrators only). Accounts are created by invitation - there is no self sign-up."""

from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Query

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError, conflict, not_found
from app.routers._shared import page_params
from app.schemas.common import OptionalShortText
from app.schemas.requests import InviteIn, PrivacyDecisionIn, TeamUpdateIn
from app.security import ratelimit
from app.security.auth import Principal, require
from app.security.context import RequestContext, get_context
from app.services import audit, supabase

router = APIRouter(prefix="/team", tags=["team"])

BAN_FOREVER = "876000h"


@router.get("")
def list_team(
    q: OptionalShortText = "",
    role: Literal["nurse", "physician", "biomed", "admin", "all"] = "all",
    status: Literal["active", "inactive", "all"] = "all",
    page: int = Query(default=1, ge=1, le=1000),
    page_size: int = Query(default=50, ge=1, le=100),
    principal: Principal = Depends(require("team:manage")),
    conn: psycopg.Connection = Depends(get_db),
) -> dict:
    where = ["true"]
    params: dict = {}
    if q:
        where.append("(p.full_name ilike %(q)s or p.email ilike %(q)s)")
        params["q"] = "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    if role != "all":
        where.append("p.role = %(role)s")
        params["role"] = role
    if status != "all":
        where.append("p.active = %(active)s")
        params["active"] = status == "active"
    limit, offset = page_params(page, page_size)
    params.update({"limit": limit, "offset": offset})
    rows = conn.execute(
        f"""select p.id, p.email, p.full_name, p.role, p.job_title, p.phone, p.active, p.avatar_path,
                   p.last_sign_in_at, p.created_at, p.anonymized_at,
                   (select count(*) from public.user_sessions s where s.user_id = p.id and s.revoked_at is null
                      and s.expires_at > now()) as active_sessions
            from public.profiles p where {' and '.join(where)}
            order by p.active desc, p.full_name limit %(limit)s offset %(offset)s""",
        params,
    ).fetchall()
    paths = [r["avatar_path"] for r in rows if r["avatar_path"]]
    try:
        signed = supabase.storage_sign("avatars", paths, expires_in=3600)
    except supabase.SupabaseError:
        signed = {}
    items = [{**{k: v for k, v in r.items() if k != "avatar_path"}, "avatar_url": signed.get(r["avatar_path"] or ""),
              "is_self": r["id"] == principal.id} for r in rows]
    return {"items": items}


@router.post("/invite", status_code=201)
def invite(body: InviteIn, principal: Principal = Depends(require("team:manage")), conn: psycopg.Connection = Depends(get_db),
           ctx: RequestContext = Depends(get_context)) -> dict:
    ratelimit.hit(conn, f"invite:{principal.id}", limit=20, window_seconds=3600)
    if conn.execute("select 1 from public.profiles where email = %s", (body.email,)).fetchone():
        raise conflict("A team member with this e-mail already exists.")
    try:
        user = supabase.admin_invite(body.email, f"{get_settings().app_url}/accept-invite", {"full_name": body.full_name})
    except supabase.SupabaseError as exc:
        if exc.status == 422:
            raise conflict("This e-mail address cannot be invited (it may already be registered).") from exc
        raise ApiError(502, "upstream_error", "The invitation could not be sent. Try again later.") from exc
    conn.execute(
        """insert into public.profiles (id, email, full_name, role, job_title, active)
           values (%s, %s, %s, %s, %s, true)""",
        (user["id"], body.email, body.full_name, body.role, body.job_title or None),
    )
    audit.record(conn, "team.invite", actor=principal, entity_type="profile", entity_id=user["id"],
                 details={"role": body.role}, ctx=ctx)
    return {"id": user["id"], "email": body.email, "role": body.role}


def _revoke_sessions(conn: psycopg.Connection, user_id: UUID, reason: str) -> None:
    conn.execute(
        "update public.user_sessions set revoked_at = now(), revoked_reason = %s where user_id = %s and revoked_at is null",
        (reason, user_id),
    )


@router.patch("/{user_id}")
def update_member(user_id: UUID, body: TeamUpdateIn, principal: Principal = Depends(require("team:manage")),
                  conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    if user_id == principal.id:
        # Separation of duties: nobody can elevate, demote or deactivate their own account.
        raise ApiError(403, "forbidden", "You cannot change your own role or status. Ask another administrator.")
    member = conn.execute("select id, role, active, anonymized_at from public.profiles where id = %s for update",
                          (user_id,)).fetchone()
    if member is None:
        raise not_found("Team member")
    if member["anonymized_at"]:
        raise conflict("This account was anonymized and cannot be changed.")
    if body.role is not None and body.role != member["role"]:
        if member["role"] == "admin":
            admins = conn.execute("select count(*) as n from public.profiles where role = 'admin' and active").fetchone()["n"]
            if admins <= 1:
                raise conflict("The ward needs at least one active administrator.")
        conn.execute("update public.profiles set role = %s, updated_at = now() where id = %s", (body.role, user_id))
        _revoke_sessions(conn, user_id, "role_changed")  # new permissions apply from the next sign-in
    if body.active is not None and body.active != member["active"]:
        conn.execute("update public.profiles set active = %s, updated_at = now() where id = %s", (body.active, user_id))
        supabase.admin_update_user(str(user_id), {"ban_duration": "none" if body.active else BAN_FOREVER})
        if not body.active:
            _revoke_sessions(conn, user_id, "deactivated")
    audit.record(conn, "team.update", actor=principal, entity_type="profile", entity_id=str(user_id),
                 details=body.model_dump(exclude_none=True), ctx=ctx)
    return {"ok": True}


@router.post("/{user_id}/anonymize")
def anonymize(user_id: UUID, principal: Principal = Depends(require("team:manage")), conn: psycopg.Connection = Depends(get_db),
              ctx: RequestContext = Depends(get_context)) -> dict:
    """Right to erasure for staff: removes personal data, keeps an anonymous record for clinical integrity."""
    if user_id == principal.id:
        raise ApiError(403, "forbidden", "You cannot anonymize your own account.")
    member = conn.execute("select id, avatar_path, anonymized_at, role from public.profiles where id = %s for update",
                          (user_id,)).fetchone()
    if member is None:
        raise not_found("Team member")
    if member["anonymized_at"]:
        raise conflict("This account is already anonymized.")
    if member["role"] == "admin":
        admins = conn.execute("select count(*) as n from public.profiles where role = 'admin' and active").fetchone()["n"]
        if admins <= 1:
            raise conflict("The ward needs at least one active administrator.")
    placeholder = f"removed-{str(user_id)[:8]}@anonymized.invalid"
    conn.execute(
        """update public.profiles set email = %s, full_name = 'Former staff member', job_title = null, phone = null,
               avatar_path = null, active = false, preferences = '{}'::jsonb, last_sign_in_ip = null,
               previous_sign_in_ip = null, anonymized_at = now(), updated_at = now() where id = %s""",
        (placeholder, user_id),
    )
    conn.execute("update public.user_sessions set ip = null, user_agent = null where user_id = %s", (user_id,))
    _revoke_sessions(conn, user_id, "anonymized")
    conn.execute("update public.alarms set acknowledged_by_name = 'Former staff member' where acknowledged_by = %s",
                 (user_id,))
    conn.execute("update public.maintenance_records set opened_by_name = 'Former staff member' where opened_by = %s",
                 (user_id,))
    conn.execute("update public.maintenance_records set completed_by_name = 'Former staff member' where completed_by = %s",
                 (user_id,))
    conn.execute("update public.reports set created_by_name = 'Former staff member' where created_by = %s", (user_id,))
    conn.execute(
        """update public.privacy_requests set status = 'completed', handled_by = %s, handled_at = now()
           where user_id = %s and status = 'pending' and kind = 'deletion'""",
        (principal.id, user_id),
    )
    supabase.admin_update_user(str(user_id), {"email": placeholder, "ban_duration": BAN_FOREVER,
                                              "user_metadata": {}})
    if member["avatar_path"]:
        try:
            supabase.storage_remove("avatars", [member["avatar_path"]])
        except supabase.SupabaseError:
            pass
    audit.record(conn, "team.anonymize", actor=principal, entity_type="profile", entity_id=str(user_id), ctx=ctx)
    return {"ok": True}


@router.get("/privacy-requests")
def privacy_requests(principal: Principal = Depends(require("privacy:manage")),
                     conn: psycopg.Connection = Depends(get_db)) -> dict:
    rows = conn.execute(
        """select r.id, r.kind, r.status, r.details, r.created_at, r.handled_at, p.full_name, p.email, p.id as user_id
           from public.privacy_requests r join public.profiles p on p.id = r.user_id
           order by (r.status = 'pending') desc, r.created_at desc limit 100"""
    ).fetchall()
    return {"items": rows}


@router.patch("/privacy-requests/{request_id}")
def decide_privacy_request(request_id: UUID, body: PrivacyDecisionIn, principal: Principal = Depends(require("privacy:manage")),
                           conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    row = conn.execute(
        """update public.privacy_requests set status = %s, handled_by = %s, handled_at = now()
           where id = %s and status = 'pending' returning id""",
        (body.status, principal.id, request_id),
    ).fetchone()
    if row is None:
        raise not_found("Pending privacy request")
    audit.record(conn, "privacy.request_decided", actor=principal, entity_type="privacy_request",
                 entity_id=str(request_id), details={"status": body.status}, ctx=ctx)
    return {"ok": True}
