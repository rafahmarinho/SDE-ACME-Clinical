"""The signed-in user's own profile, preferences, password, avatar, privacy choices and sessions."""

import io
import uuid
from datetime import UTC, datetime

import psycopg
from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from PIL import Image, UnidentifiedImageError
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError, bad_request
from app.schemas.requests import (
    ChangePasswordIn,
    ConsentIn,
    PreferencesIn,
    PrivacyRequestIn,
    ProfileUpdateIn,
)
from app.security import passwords, ratelimit
from app.security.auth import Principal, get_principal
from app.security.context import RequestContext, get_context
from app.services import audit, supabase

router = APIRouter(prefix="/me", tags=["me"])

CONSENT_VERSION = "2026-10"
Image.MAX_IMAGE_PIXELS = 16_000_000


def _avatar_url(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return supabase.storage_sign("avatars", [path], expires_in=3600).get(path)
    except supabase.SupabaseError:
        return None


@router.get("")
def get_me(principal: Principal = Depends(get_principal), conn: psycopg.Connection = Depends(get_db)) -> dict:
    p = conn.execute(
        """select id, email, full_name, role, job_title, phone, unit, avatar_path, preferences, consent_accepted_at,
                  consent_version, last_sign_in_at, last_sign_in_ip, previous_sign_in_at, previous_sign_in_ip, created_at
           from public.profiles where id = %s""",
        (principal.id,),
    ).fetchone()
    session = conn.execute("select created_at, expires_at, idle_timeout_seconds from public.user_sessions where session_id = %s",
                           (principal.session_id,)).fetchone()
    pending = conn.execute(
        "select kind, status, created_at from public.privacy_requests where user_id = %s and status = 'pending'",
        (principal.id,),
    ).fetchall()
    return {
        **{k: p[k] for k in ("id", "email", "full_name", "role", "job_title", "phone", "unit", "created_at")},
        "avatar_url": _avatar_url(p["avatar_path"]),
        "preferences": PreferencesIn(**(p["preferences"] or {})).model_dump(),
        "consent": {"accepted_at": p["consent_accepted_at"], "version": p["consent_version"],
                    "current_version": CONSENT_VERSION,
                    "required": p["consent_version"] != CONSENT_VERSION or p["consent_accepted_at"] is None},
        "previous_sign_in": {"at": p["previous_sign_in_at"], "ip": p["previous_sign_in_ip"]},
        "permissions": principal.permissions,
        "session": {"aal": principal.aal, "mfa_enrolled": principal.mfa_enrolled, **(session or {})},
        "privacy_requests": pending,
    }


@router.patch("")
def update_profile(body: ProfileUpdateIn, principal: Principal = Depends(get_principal),
                   conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    conn.execute(
        "update public.profiles set full_name = %s, job_title = %s, phone = %s, updated_at = now() where id = %s",
        (body.full_name, body.job_title or None, body.phone or None, principal.id),
    )
    audit.record(conn, "profile.update", actor=principal, entity_type="profile", entity_id=str(principal.id),
                 details={"fields": ["full_name", "job_title", "phone"]}, ctx=ctx)
    return {"ok": True}


@router.put("/preferences")
def update_preferences(body: PreferencesIn, principal: Principal = Depends(get_principal),
                       conn: psycopg.Connection = Depends(get_db)) -> dict:
    conn.execute("update public.profiles set preferences = %s, updated_at = now() where id = %s",
                 (Jsonb(body.model_dump()), principal.id))
    return body.model_dump()


@router.post("/password")
def change_password(body: ChangePasswordIn, principal: Principal = Depends(get_principal),
                    conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    ratelimit.hit(conn, f"pwchange:{principal.id}", limit=5, window_seconds=900)
    status, _ = supabase.password_grant(principal.email, body.current_password)
    if status != 200:
        audit.record(conn, "auth.password_change", actor=principal, outcome="failure",
                     details={"reason": "wrong_current_password"}, ctx=ctx)
        raise ApiError(400, "wrong_password", "Your current password is incorrect.")
    if body.new_password == body.current_password:
        raise ApiError(422, "weak_password", "Choose a password different from the current one.")
    issues = passwords.problems(body.new_password, principal.email)
    if issues:
        raise ApiError(422, "weak_password", " ".join(issues))
    try:
        supabase.admin_update_user(str(principal.id), {"password": body.new_password})
    except supabase.SupabaseError as exc:
        raise ApiError(422, "weak_password", "This password was rejected. Choose a different one.") from exc
    # Sign out every other session; keep the current one.
    conn.execute(
        """update public.user_sessions set revoked_at = now(), revoked_reason = 'password_change'
           where user_id = %s and session_id <> %s and revoked_at is null""",
        (principal.id, principal.session_id),
    )
    audit.record(conn, "auth.password_change", actor=principal, ctx=ctx)
    return {"message": "Password updated. Other sessions were signed out."}


def _process_avatar(data: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(data)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(data)) as img:
            if img.format not in ("PNG", "JPEG", "WEBP"):
                raise bad_request("Upload a PNG, JPEG or WebP image.", "unsupported_file")
            img = img.convert("RGBA")
            img.thumbnail((256, 256))
            out = io.BytesIO()
            img.save(out, format="PNG", optimize=True)  # re-encoding strips metadata and embedded payloads
            return out.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, SyntaxError) as exc:
        raise bad_request("The file is not a valid image.", "unsupported_file") from exc


@router.post("/avatar")
async def upload_avatar(file: UploadFile = File(...), principal: Principal = Depends(get_principal),
                        conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise ApiError(413, "file_too_large", "The image must be 2 MB or smaller.")
    if not data[:12].startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff")) and not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        raise bad_request("Upload a PNG, JPEG or WebP image.", "unsupported_file")
    png = _process_avatar(data)
    path = f"{principal.id}/{uuid.uuid4()}.png"  # server-chosen name: the client never controls storage paths
    old = conn.execute("select avatar_path from public.profiles where id = %s", (principal.id,)).fetchone()["avatar_path"]
    supabase.storage_upload("avatars", path, png, "image/png")
    conn.execute("update public.profiles set avatar_path = %s, updated_at = now() where id = %s", (path, principal.id))
    if old:
        try:
            supabase.storage_remove("avatars", [old])
        except supabase.SupabaseError:
            pass
    audit.record(conn, "profile.avatar_upload", actor=principal, details={"bytes": len(png)}, ctx=ctx)
    return {"avatar_url": _avatar_url(path)}


@router.delete("/avatar")
def delete_avatar(principal: Principal = Depends(get_principal), conn: psycopg.Connection = Depends(get_db),
                  ctx: RequestContext = Depends(get_context)) -> dict:
    old = conn.execute("select avatar_path from public.profiles where id = %s", (principal.id,)).fetchone()["avatar_path"]
    conn.execute("update public.profiles set avatar_path = null, updated_at = now() where id = %s", (principal.id,))
    if old:
        try:
            supabase.storage_remove("avatars", [old])
        except supabase.SupabaseError:
            pass
    audit.record(conn, "profile.avatar_delete", actor=principal, ctx=ctx)
    return {"ok": True}


@router.post("/consent")
def accept_consent(body: ConsentIn, principal: Principal = Depends(get_principal),
                   conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    conn.execute("update public.profiles set consent_accepted_at = now(), consent_version = %s where id = %s",
                 (body.version, principal.id))
    audit.record(conn, "privacy.consent_accepted", actor=principal, details={"version": body.version}, ctx=ctx)
    return {"accepted": True, "version": body.version}


@router.post("/consent/withdraw")
def withdraw_consent(principal: Principal = Depends(get_principal), conn: psycopg.Connection = Depends(get_db),
                     ctx: RequestContext = Depends(get_context)) -> dict:
    conn.execute("update public.profiles set consent_accepted_at = null, consent_version = null where id = %s",
                 (principal.id,))
    conn.execute("insert into public.privacy_requests (user_id, kind) values (%s, 'consent_withdrawal')", (principal.id,))
    conn.execute(
        """insert into public.integration_outbox (channel, recipient, subject, payload)
           values ('privacy_office', 'privacy-office', 'Consent withdrawn', %s)""",
        (Jsonb({"user_id": str(principal.id)}),),
    )
    audit.record(conn, "privacy.consent_withdrawn", actor=principal, ctx=ctx)
    return {"withdrawn": True}


@router.post("/privacy-requests")
def create_privacy_request(body: PrivacyRequestIn, principal: Principal = Depends(get_principal),
                           conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    existing = conn.execute(
        "select 1 from public.privacy_requests where user_id = %s and kind = %s and status = 'pending'",
        (principal.id, body.kind),
    ).fetchone()
    if existing:
        raise ApiError(409, "conflict", "You already have a pending request of this type.")
    row = conn.execute(
        "insert into public.privacy_requests (user_id, kind, details) values (%s, %s, %s) returning id, created_at",
        (principal.id, body.kind, body.details or None),
    ).fetchone()
    audit.record(conn, "privacy.request_created", actor=principal, entity_type="privacy_request",
                 entity_id=str(row["id"]), details={"kind": body.kind}, ctx=ctx)
    return {"id": row["id"], "status": "pending"}


@router.get("/export")
def export_my_data(principal: Principal = Depends(get_principal), conn: psycopg.Connection = Depends(get_db),
                   ctx: RequestContext = Depends(get_context)) -> JSONResponse:
    ratelimit.hit(conn, f"export:{principal.id}", limit=5, window_seconds=3600)
    profile = conn.execute(
        """select id, email, full_name, role, job_title, phone, unit, preferences, consent_accepted_at, consent_version,
                  last_sign_in_at, last_sign_in_ip, previous_sign_in_at, previous_sign_in_ip, created_at, updated_at
           from public.profiles where id = %s""",
        (principal.id,),
    ).fetchone()
    sessions = conn.execute(
        """select created_at, last_seen_at, expires_at, ip, user_agent, revoked_at, revoked_reason
           from public.user_sessions where user_id = %s order by created_at desc limit 100""",
        (principal.id,),
    ).fetchall()
    activity = conn.execute(
        """select created_at, action, entity_type, entity_id, outcome, ip from public.audit_log
           where actor_id = %s order by id desc limit 500""",
        (principal.id,),
    ).fetchall()
    notes = conn.execute("select count(*) as n from public.notes where author_id = %s", (principal.id,)).fetchone()
    requests = conn.execute("select kind, status, created_at, handled_at from public.privacy_requests where user_id = %s",
                            (principal.id,)).fetchall()
    audit.record(conn, "privacy.data_export", actor=principal, ctx=ctx)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "purpose": "Personal data held by ACME Clinical about your staff account.",
        "profile": profile, "sessions": sessions, "activity": activity,
        "clinical_notes_authored": notes["n"], "privacy_requests": requests,
    }
    return JSONResponse(jsonable_encoder(payload),
                        headers={"Content-Disposition": 'attachment; filename="acme-clinical-my-data.json"'})


@router.get("/sessions")
def my_sessions(principal: Principal = Depends(get_principal), conn: psycopg.Connection = Depends(get_db)) -> dict:
    rows = conn.execute(
        """select session_id, created_at, last_seen_at, expires_at, ip, user_agent
           from public.user_sessions where user_id = %s and revoked_at is null and expires_at > now()
           order by created_at desc""",
        (principal.id,),
    ).fetchall()
    return {"items": [{**r, "current": r["session_id"] == principal.session_id} for r in rows]}


@router.post("/sessions/revoke-others")
def revoke_other_sessions(principal: Principal = Depends(get_principal), conn: psycopg.Connection = Depends(get_db),
                          ctx: RequestContext = Depends(get_context)) -> dict:
    rows = conn.execute(
        """update public.user_sessions set revoked_at = now(), revoked_reason = 'user_revoked'
           where user_id = %s and session_id <> %s and revoked_at is null returning session_id""",
        (principal.id, principal.session_id),
    ).fetchall()
    audit.record(conn, "auth.sessions_revoked", actor=principal, details={"count": len(rows)}, ctx=ctx)
    return {"revoked": len(rows)}
