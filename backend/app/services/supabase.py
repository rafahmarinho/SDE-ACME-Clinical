"""Server-side gateway to Supabase Auth (GoTrue) and Storage.

The service-role/secret key only lives in the API environment. All calls use HTTPS with
certificate verification (httpx default) and short timeouts. URLs are built from configuration,
never from user input (no SSRF surface).
"""

from typing import Any
from urllib.parse import quote

import httpx

from app.config import get_settings

# Tests and the offline demo stack inject a transport here (e.g. httpx.ASGITransport).
transport: httpx.BaseTransport | None = None
_client: httpx.Client | None = None


class SupabaseError(Exception):
    def __init__(self, status: int, body: Any):
        super().__init__(f"Supabase request failed with status {status}")
        self.status = status
        self.body = body


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            base_url=get_settings().supabase_url,
            timeout=httpx.Timeout(10.0, connect=5.0),
            transport=transport,
            follow_redirects=False,
        )
    return _client


def reset_client() -> None:
    global _client
    if _client is not None:
        _client.close()
    _client = None


def _key_headers(key: str) -> dict[str, str]:
    headers = {"apikey": key}
    if key.startswith("eyJ"):  # legacy JWT-format keys are also sent as bearer
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _anon() -> dict[str, str]:
    return _key_headers(get_settings().supabase_anon_key)


def _service() -> dict[str, str]:
    return _key_headers(get_settings().supabase_service_role_key)


def _json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return {}


def _check(resp: httpx.Response) -> Any:
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _json(resp))
    return _json(resp)


# --------------------------------------------------------------------------- Auth
def password_grant(email: str, password: str) -> tuple[int, dict[str, Any]]:
    resp = client().post(
        "/auth/v1/token", params={"grant_type": "password"}, json={"email": email, "password": password}, headers=_anon()
    )
    return resp.status_code, _json(resp)


def get_user(access_token: str) -> dict[str, Any]:
    resp = client().get("/auth/v1/user", headers={**_anon(), "Authorization": f"Bearer {access_token}"})
    return _check(resp)


def logout(access_token: str, scope: str = "local") -> None:
    resp = client().post(
        "/auth/v1/logout", params={"scope": scope}, headers={**_anon(), "Authorization": f"Bearer {access_token}"}
    )
    if resp.status_code not in (204, 200, 401, 403, 404):
        raise SupabaseError(resp.status_code, _json(resp))


def recover(email: str, redirect_to: str) -> None:
    resp = client().post("/auth/v1/recover", params={"redirect_to": redirect_to}, json={"email": email}, headers=_anon())
    if resp.status_code >= 500:
        raise SupabaseError(resp.status_code, _json(resp))


def admin_create_user(email: str, password: str, metadata: dict[str, Any]) -> dict[str, Any]:
    resp = client().post(
        "/auth/v1/admin/users",
        json={"email": email, "password": password, "email_confirm": True, "user_metadata": metadata},
        headers=_service(),
    )
    return _check(resp)


def admin_invite(email: str, redirect_to: str, metadata: dict[str, Any]) -> dict[str, Any]:
    resp = client().post(
        "/auth/v1/invite", params={"redirect_to": redirect_to}, json={"email": email, "data": metadata}, headers=_service()
    )
    return _check(resp)


def admin_update_user(user_id: str, attributes: dict[str, Any]) -> dict[str, Any]:
    resp = client().put(f"/auth/v1/admin/users/{quote(user_id)}", json=attributes, headers=_service())
    return _check(resp)


def admin_find_user_by_email(email: str) -> dict[str, Any] | None:
    page = 1
    while page < 50:
        resp = client().get("/auth/v1/admin/users", params={"page": page, "per_page": 200}, headers=_service())
        users = _check(resp).get("users", [])
        for user in users:
            if (user.get("email") or "").lower() == email:
                return user
        if len(users) < 200:
            return None
        page += 1
    return None


# --------------------------------------------------------------------------- Storage
def storage_upload(bucket: str, path: str, data: bytes, content_type: str) -> None:
    resp = client().post(
        f"/storage/v1/object/{bucket}/{quote(path)}",
        content=data,
        headers={**_service(), "Content-Type": content_type, "x-upsert": "false", "cache-control": "no-store"},
    )
    _check(resp)


def storage_download(bucket: str, path: str) -> bytes:
    resp = client().get(f"/storage/v1/object/authenticated/{bucket}/{quote(path)}", headers=_service())
    if resp.status_code >= 400:
        raise SupabaseError(resp.status_code, _json(resp))
    return resp.content


def storage_sign(bucket: str, paths: list[str], expires_in: int = 300) -> dict[str, str]:
    if not paths:
        return {}
    resp = client().post(
        f"/storage/v1/object/sign/{bucket}", json={"expiresIn": expires_in, "paths": paths}, headers=_service()
    )
    out: dict[str, str] = {}
    for item in _check(resp) or []:
        signed = item.get("signedURL")
        if signed and not item.get("error"):
            out[item["path"]] = f"{get_settings().supabase_url}/storage/v1{signed}"
    return out


def storage_remove(bucket: str, paths: list[str]) -> None:
    if not paths:
        return
    resp = client().request("DELETE", f"/storage/v1/object/{bucket}", json={"prefixes": paths}, headers=_service())
    if resp.status_code >= 500:
        raise SupabaseError(resp.status_code, _json(resp))
