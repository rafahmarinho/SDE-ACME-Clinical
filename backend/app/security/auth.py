"""Authentication and session enforcement for every API request.

1. The bearer token must be a valid Supabase JWT (signature via JWKS or the legacy HS256 secret,
   audience, issuer, expiry).
2. Its `session_id` must belong to a session created through POST /auth/login and must not be
   revoked, idle for longer than IDLE_TIMEOUT_MINUTES or older than ABSOLUTE_TIMEOUT_HOURS.
3. The staff profile must exist and be active.
4. Accounts with a verified second factor must present an AAL2 token.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import lru_cache
from uuid import UUID

import jwt
import psycopg
from fastapi import Depends, Request

from app.config import get_settings
from app.db import get_db
from app.errors import ApiError, forbidden, unauthorized
from app.security import authz
from app.security.context import RequestContext, get_context
from app.services import audit


@dataclass
class Principal:
    id: UUID
    email: str
    role: str
    full_name: str
    session_id: UUID
    aal: str
    mfa_enrolled: bool
    access_token: str = field(repr=False)

    @property
    def permissions(self) -> list[str]:
        return authz.permissions_for(self.role)

    def can(self, permission: str) -> bool:
        return authz.allowed(self.role, permission)


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    url = f"{get_settings().supabase_url}/auth/v1/.well-known/jwks.json"
    return jwt.PyJWKClient(url, cache_jwk_set=True, lifespan=600, timeout=5)


def verify_token(token: str) -> dict:
    settings = get_settings()
    try:
        header = jwt.get_unverified_header(token)
        alg = header.get("alg")
        if alg == "HS256" and settings.supabase_jwt_secret:
            key = settings.supabase_jwt_secret
        elif alg in ("ES256", "RS256", "EdDSA"):
            key = _jwks_client().get_signing_key_from_jwt(token).key
        else:
            raise jwt.InvalidTokenError("unsupported algorithm")
        claims = jwt.decode(
            token,
            key,
            algorithms=[alg],
            audience="authenticated",
            issuer=f"{settings.supabase_url}/auth/v1",
            options={"require": ["exp", "iat", "sub", "session_id"]},
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        raise unauthorized("invalid_token", "Your session is invalid. Please sign in again.") from exc
    if claims.get("is_anonymous"):
        raise unauthorized("invalid_token", "Your session is invalid. Please sign in again.")
    return claims


def bearer_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token or len(token) > 8192:
        raise unauthorized()
    return token.strip()


def _expire(conn: psycopg.Connection, session_id: str, reason: str) -> None:
    conn.execute(
        "update public.user_sessions set revoked_at = now(), revoked_reason = %s where session_id = %s and revoked_at is null",
        (reason, session_id),
    )


def get_principal(
    request: Request,
    conn: psycopg.Connection = Depends(get_db),
    ctx: RequestContext = Depends(get_context),
) -> Principal:
    token = bearer_token(request)
    claims = verify_token(token)
    try:
        user_id = UUID(claims["sub"])
        session_id = UUID(claims["session_id"])
    except (ValueError, TypeError) as exc:
        raise unauthorized("invalid_token", "Your session is invalid. Please sign in again.") from exc

    row = conn.execute(
        """select p.id, p.email, p.role, p.full_name, p.active,
                  s.session_id, s.revoked_at, s.expires_at, s.last_seen_at, s.idle_timeout_seconds, s.mfa_enrolled
           from public.profiles p
           left join public.user_sessions s on s.session_id = %s and s.user_id = p.id
           where p.id = %s""",
        (session_id, user_id),
    ).fetchone()
    if row is None or not row["active"]:
        raise unauthorized("account_inactive", "Your account is not active. Contact an administrator.")
    if row["session_id"] is None or row["revoked_at"] is not None:
        raise unauthorized("session_revoked", "You have been signed out. Please sign in again.")
    now = datetime.now(UTC)
    if row["expires_at"] <= now:
        _expire(conn, str(session_id), "absolute_timeout")
        audit.record(conn, "session.expired", actor_email=row["email"], entity_type="session",
                     entity_id=str(session_id), details={"reason": "absolute_timeout"}, ctx=ctx)
        raise unauthorized("session_expired", "Your session has expired. Please sign in again.")
    if (now - row["last_seen_at"]).total_seconds() > row["idle_timeout_seconds"]:
        _expire(conn, str(session_id), "idle_timeout")
        audit.record(conn, "session.expired", actor_email=row["email"], entity_type="session",
                     entity_id=str(session_id), details={"reason": "idle_timeout"}, ctx=ctx)
        raise unauthorized("session_expired", "You were signed out after a period of inactivity.")

    aal = str(claims.get("aal") or "aal1")
    if row["mfa_enrolled"] and aal != "aal2":
        raise unauthorized("mfa_required", "Enter your two-factor authentication code to continue.")

    principal = Principal(
        id=user_id,
        email=row["email"],
        role=row["role"],
        full_name=row["full_name"],
        session_id=session_id,
        aal=aal,
        mfa_enrolled=row["mfa_enrolled"],
        access_token=token,
    )
    request.state.principal = principal
    return principal


def require(permission: str):
    """Dependency factory enforcing one permission from the central policy."""

    def dependency(
        principal: Principal = Depends(get_principal),
        conn: psycopg.Connection = Depends(get_db),
        ctx: RequestContext = Depends(get_context),
    ) -> Principal:
        if not principal.can(permission):
            audit.record(conn, "authz.denied", actor=principal, outcome="denied",
                         details={"permission": permission}, ctx=ctx)
            raise forbidden()
        if permission in authz.MFA_PROTECTED and get_settings().require_admin_mfa and principal.aal != "aal2":
            audit.record(conn, "authz.mfa_required", actor=principal, outcome="denied",
                         details={"permission": permission}, ctx=ctx)
            raise ApiError(403, "mfa_required_admin",
                           "Administrative actions require two-factor authentication. Set it up in Settings > Security.")
        return principal

    return dependency
