"""Sign-in, sign-out, session heartbeat, password recovery and reset.

Sign-in is proxied through the API so that the application - not only the identity provider -
can enforce lockout, uniform error messages, random failure delays, session bookkeeping
(idle/absolute timeout, concurrent session limit) and previous-login notification.
"""

import random
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError, bad_request, unauthorized
from app.schemas.requests import LoginIn, RecoverIn, ResetPasswordIn
from app.security import passwords, ratelimit
from app.security.auth import Principal, get_principal, verify_token
from app.security.context import RequestContext, get_context
from app.security.crypto import hash_identifier
from app.services import audit, supabase

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_LOGIN = "Invalid e-mail or password."
LOCKED_LOGIN = "Too many failed sign-in attempts. Try again later or reset your password."


def _failure_delay() -> None:
    time.sleep(random.SystemRandom().uniform(0.25, 0.75))


def _register_failure(conn: psycopg.Connection, key: str) -> None:
    settings = get_settings()
    conn.execute(
        """insert into public.auth_throttle (key, failures, first_failure_at) values (%(k)s, 1, now())
           on conflict (key) do update set
             failures = case when public.auth_throttle.first_failure_at < now() - make_interval(mins => %(w)s)
                             then 1 else public.auth_throttle.failures + 1 end,
             first_failure_at = case when public.auth_throttle.first_failure_at < now() - make_interval(mins => %(w)s)
                             then now() else public.auth_throttle.first_failure_at end""",
        {"k": key, "w": settings.lockout_minutes},
    )
    conn.execute(
        """update public.auth_throttle set locked_until = now() + make_interval(mins => %s)
           where key = %s and failures >= %s""",
        (settings.lockout_minutes, key, settings.login_max_failures),
    )


@router.get("/policy")
def password_policy() -> dict:
    settings = get_settings()
    return {
        "password": passwords.policy(),
        "idle_timeout_minutes": settings.idle_timeout_minutes,
        "absolute_timeout_hours": settings.absolute_timeout_hours,
    }


@router.post("/login")
def login(body: LoginIn, conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    settings = get_settings()
    ratelimit.hit(conn, f"login-ip:{ctx.ip}", limit=settings.login_ip_limit_per_5min, window_seconds=300)
    key = hash_identifier(body.email)
    throttle = conn.execute("select locked_until from public.auth_throttle where key = %s", (key,)).fetchone()
    if throttle and throttle["locked_until"] and throttle["locked_until"] > datetime.now(UTC):
        audit.record(conn, "auth.login", actor_email=body.email, outcome="denied", details={"reason": "locked"}, ctx=ctx)
        _failure_delay()
        raise ApiError(429, "account_locked", LOCKED_LOGIN, headers={"Retry-After": str(settings.lockout_minutes * 60)})

    status, data = supabase.password_grant(body.email, body.password)
    if status != 200 or "access_token" not in data:
        _register_failure(conn, key)
        audit.record(conn, "auth.login", actor_email=body.email, outcome="failure",
                     details={"reason": "invalid_credentials" if status in (400, 401, 422) else f"idp_{status}"}, ctx=ctx)
        _failure_delay()
        if status >= 500:
            raise ApiError(503, "auth_unavailable", "Sign-in is temporarily unavailable. Please try again shortly.")
        raise unauthorized("invalid_credentials", INVALID_LOGIN)

    claims = verify_token(data["access_token"])
    user_id = UUID(claims["sub"])
    profile = conn.execute(
        "select id, email, role, full_name, active, last_sign_in_at, last_sign_in_ip from public.profiles where id = %s",
        (user_id,),
    ).fetchone()
    if profile is None or not profile["active"]:
        supabase.logout(data["access_token"], scope="global")
        _register_failure(conn, key)
        audit.record(conn, "auth.login", actor_email=body.email, outcome="denied", details={"reason": "inactive"}, ctx=ctx)
        _failure_delay()
        raise unauthorized("invalid_credentials", INVALID_LOGIN)

    conn.execute("delete from public.auth_throttle where key = %s", (key,))
    factors = (data.get("user") or {}).get("factors") or []
    mfa_enrolled = any(f.get("status") == "verified" for f in factors)
    now = datetime.now(UTC)
    conn.execute(
        """insert into public.user_sessions (session_id, user_id, created_at, last_seen_at, expires_at,
               idle_timeout_seconds, mfa_enrolled, ip, user_agent)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s)
           on conflict (session_id) do nothing""",
        (claims["session_id"], user_id, now, now, now + timedelta(hours=settings.absolute_timeout_hours),
         settings.idle_timeout_minutes * 60, mfa_enrolled, ctx.ip, ctx.user_agent),
    )
    # Concurrent session limit: revoke the oldest active sessions beyond the maximum.
    revoked = conn.execute(
        """update public.user_sessions set revoked_at = now(), revoked_reason = 'session_limit'
           where session_id in (
             select session_id from public.user_sessions
             where user_id = %s and revoked_at is null and expires_at > now()
             order by created_at desc offset %s)
           returning session_id""",
        (user_id, settings.max_concurrent_sessions),
    ).fetchall()
    conn.execute(
        """update public.profiles set previous_sign_in_at = last_sign_in_at, previous_sign_in_ip = last_sign_in_ip,
               last_sign_in_at = now(), last_sign_in_ip = %s where id = %s""",
        (ctx.ip, user_id),
    )
    audit.record(conn, "auth.login", actor_email=profile["email"], entity_type="session",
                 entity_id=str(claims["session_id"]), details={"revoked_old_sessions": len(revoked),
                                                               "mfa_enrolled": mfa_enrolled}, ctx=ctx)
    return {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token"),
        "expires_in": data.get("expires_in"),
        "token_type": "bearer",
        "mfa_required": mfa_enrolled,
        "previous_sign_in": {"at": profile["last_sign_in_at"], "ip": profile["last_sign_in_ip"]},
    }


@router.post("/logout")
def logout(principal: Principal = Depends(get_principal), conn: psycopg.Connection = Depends(get_db),
           ctx: RequestContext = Depends(get_context)) -> dict:
    conn.execute(
        "update public.user_sessions set revoked_at = now(), revoked_reason = 'logout' where session_id = %s",
        (principal.session_id,),
    )
    try:
        supabase.logout(principal.access_token, scope="local")
    except supabase.SupabaseError:
        pass  # local revocation above already blocks the session in the API and RLS
    audit.record(conn, "auth.logout", actor=principal, entity_type="session", entity_id=str(principal.session_id), ctx=ctx)
    return {"ok": True}


@router.post("/heartbeat")
def heartbeat(principal: Principal = Depends(get_principal), conn: psycopg.Connection = Depends(get_db)) -> dict:
    """Called by the browser only when the user is actively interacting (keyboard/mouse/touch)."""
    row = conn.execute(
        """update public.user_sessions set last_seen_at = now() where session_id = %s
           returning expires_at, idle_timeout_seconds""",
        (principal.session_id,),
    ).fetchone()
    return {"expires_at": row["expires_at"], "idle_timeout_seconds": row["idle_timeout_seconds"]}


@router.post("/mfa/sync")
def mfa_sync(principal: Principal = Depends(get_principal), conn: psycopg.Connection = Depends(get_db),
             ctx: RequestContext = Depends(get_context)) -> dict:
    """Refresh the session's MFA requirement after the user enrolls or removes a factor."""
    user = supabase.get_user(principal.access_token)
    enrolled = any(f.get("status") == "verified" for f in (user.get("factors") or []))
    conn.execute("update public.user_sessions set mfa_enrolled = %s where user_id = %s and revoked_at is null",
                 (enrolled, principal.id))
    audit.record(conn, "auth.mfa_sync", actor=principal, details={"enrolled": enrolled}, ctx=ctx)
    return {"mfa_enrolled": enrolled}


@router.post("/recover")
def recover(body: RecoverIn, conn: psycopg.Connection = Depends(get_db), ctx: RequestContext = Depends(get_context)) -> dict:
    """Always answers the same way, whether or not the account exists (no user enumeration)."""
    ratelimit.hit(conn, f"recover-ip:{ctx.ip}", limit=10, window_seconds=900)
    ratelimit.hit(conn, f"recover-email:{hash_identifier(body.email)}", limit=3, window_seconds=900)
    try:
        supabase.recover(body.email, f"{get_settings().app_url}/reset-password")
    except supabase.SupabaseError:
        pass
    audit.record(conn, "auth.recover_requested", actor_email=body.email, ctx=ctx)
    return {"message": "If an account exists for this address, we sent a link to reset the password."}


@router.post("/reset-password")
def reset_password(body: ResetPasswordIn, conn: psycopg.Connection = Depends(get_db),
                   ctx: RequestContext = Depends(get_context)) -> dict:
    """Completes a recovery or invitation link: the one-time link token proves control of the mailbox."""
    ratelimit.hit(conn, f"reset-ip:{ctx.ip}", limit=10, window_seconds=900)
    claims = verify_token(body.access_token)
    methods = {m.get("method") for m in claims.get("amr") or [] if isinstance(m, dict)}
    if not methods & {"recovery", "invite", "otp", "magiclink"}:
        raise bad_request("This link is not a password reset link.", "invalid_link")
    user_id = claims["sub"]
    profile = conn.execute("select email, active from public.profiles where id = %s", (user_id,)).fetchone()
    if profile is None or not profile["active"]:
        raise bad_request("This link is no longer valid.", "invalid_link")
    issues = passwords.problems(body.new_password, profile["email"])
    if issues:
        raise ApiError(422, "weak_password", " ".join(issues))
    try:
        supabase.admin_update_user(user_id, {"password": body.new_password})
    except supabase.SupabaseError as exc:
        raise ApiError(422, "weak_password", "This password was rejected. Choose a different one.") from exc
    try:
        supabase.logout(body.access_token, scope="global")
    except supabase.SupabaseError:
        pass
    conn.execute("""update public.user_sessions set revoked_at = now(), revoked_reason = 'password_reset'
                    where user_id = %s and revoked_at is null""", (user_id,))
    conn.execute("delete from public.auth_throttle where key = %s", (hash_identifier(profile["email"]),))
    audit.record(conn, "auth.password_reset", actor_email=profile["email"], entity_type="user", entity_id=str(user_id),
                 ctx=ctx)
    return {"message": "Your password has been updated. Sign in with your new password."}

