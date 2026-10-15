"""In-memory stand-in for the subset of Supabase Auth (GoTrue) and Storage used by ACME Clinical.

TEST / OFFLINE-DEMO TOOLING ONLY. It issues HS256 tokens signed with SUPABASE_JWT_SECRET and keeps
everything in memory. It is excluded from deployments (.vercelignore) and never used in production.
"""

import os
import time
import uuid
from typing import Any

import jwt
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

USERS: dict[str, dict[str, Any]] = {}
SESSIONS: dict[str, dict[str, Any]] = {}
REFRESH: dict[str, str] = {}
OBJECTS: dict[tuple[str, str], tuple[bytes, str]] = {}
OUTBOX: list[dict[str, Any]] = []


def reset() -> None:
    USERS.clear()
    SESSIONS.clear()
    REFRESH.clear()
    OBJECTS.clear()
    OUTBOX.clear()


def _cfg() -> tuple[str, str, str, str]:
    return (os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_JWT_SECRET"],
            os.environ["SUPABASE_ANON_KEY"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def add_user(email: str, password: str | None, user_id: str | None = None, factors: list | None = None) -> dict:
    user = {"id": user_id or str(uuid.uuid4()), "email": email.lower(), "password": password, "banned": False,
            "factors": factors or [], "user_metadata": {}}
    USERS[user["id"]] = user
    return user


def find_user(email: str) -> dict | None:
    return next((u for u in USERS.values() if u["email"] == email.lower()), None)


def issue_token(user: dict, session_id: str | None = None, aal: str = "aal1", method: str = "password",
                ttl: int = 3600) -> str:
    base, secret, _, _ = _cfg()
    now = int(time.time())
    claims = {
        "aud": "authenticated", "iss": f"{base}/auth/v1", "sub": user["id"], "email": user["email"],
        "role": "authenticated", "aal": aal, "amr": [{"method": method, "timestamp": now}],
        "session_id": session_id or str(uuid.uuid4()), "iat": now, "exp": now + ttl, "is_anonymous": False,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def _session_response(user: dict, session_id: str, aal: str = "aal1") -> dict:
    refresh = uuid.uuid4().hex
    REFRESH[refresh] = session_id
    SESSIONS[session_id] = {"user_id": user["id"], "aal": aal}
    public_user = {"id": user["id"], "email": user["email"], "aud": "authenticated", "role": "authenticated",
                   "factors": user["factors"], "user_metadata": user["user_metadata"], "app_metadata": {}}
    return {"access_token": issue_token(user, session_id, aal), "token_type": "bearer", "expires_in": 3600,
            "expires_at": int(time.time()) + 3600, "refresh_token": refresh, "user": public_user}


def _bearer_user(request: Request) -> dict | None:
    _, secret, _, _ = _cfg()
    token = request.headers.get("authorization", "")[7:]
    try:
        claims = jwt.decode(token, secret, algorithms=["HS256"], audience="authenticated")
    except jwt.PyJWTError:
        return None
    if claims.get("session_id") not in SESSIONS and claims["amr"][0]["method"] == "password":
        return None
    return USERS.get(claims["sub"])


def _is_service(request: Request) -> bool:
    return request.headers.get("apikey") == _cfg()[3]


app = FastAPI(title="Mock Supabase (tests only)")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.post("/auth/v1/token")
async def token(request: Request, grant_type: str) -> Response:
    body = await request.json()
    if grant_type == "password":
        user = find_user(body.get("email", ""))
        if user is None or user["password"] is None or user["password"] != body.get("password") or user["banned"]:
            return JSONResponse({"code": 400, "error_code": "invalid_credentials",
                                 "msg": "Invalid login credentials"}, status_code=400)
        return JSONResponse(_session_response(user, str(uuid.uuid4())))
    if grant_type == "refresh_token":
        session_id = REFRESH.pop(body.get("refresh_token", ""), None)
        if session_id is None or session_id not in SESSIONS:
            return JSONResponse({"error_code": "refresh_token_not_found"}, status_code=400)
        user = USERS[SESSIONS[session_id]["user_id"]]
        return JSONResponse(_session_response(user, session_id, SESSIONS[session_id]["aal"]))
    return JSONResponse({"error_code": "unsupported_grant_type"}, status_code=400)


@app.get("/auth/v1/user")
def get_user(request: Request) -> Response:
    user = _bearer_user(request)
    if user is None:
        return JSONResponse({"error_code": "bad_jwt"}, status_code=401)
    return JSONResponse({"id": user["id"], "email": user["email"], "factors": user["factors"],
                         "user_metadata": user["user_metadata"], "app_metadata": {}, "aud": "authenticated"})


@app.post("/auth/v1/logout")
def logout(request: Request, scope: str = "local") -> Response:
    _, secret, _, _ = _cfg()
    try:
        claims = jwt.decode(request.headers.get("authorization", "")[7:], secret, algorithms=["HS256"],
                            audience="authenticated")
        if scope == "global":
            for sid in [s for s, v in SESSIONS.items() if v["user_id"] == claims["sub"]]:
                SESSIONS.pop(sid, None)
        else:
            SESSIONS.pop(claims.get("session_id"), None)
    except jwt.PyJWTError:
        pass
    return Response(status_code=204)


@app.post("/auth/v1/recover")
async def recover(request: Request, redirect_to: str = "") -> Response:
    body = await request.json()
    user = find_user(body.get("email", ""))
    if user:
        OUTBOX.append({"type": "recovery", "email": user["email"], "redirect_to": redirect_to,
                       "token": issue_token(user, method="recovery")})
    return JSONResponse({})


@app.post("/auth/v1/admin/users")
async def admin_create(request: Request) -> Response:
    if not _is_service(request):
        return JSONResponse({"msg": "forbidden"}, status_code=403)
    body = await request.json()
    if find_user(body["email"]):
        return JSONResponse({"error_code": "email_exists", "msg": "already registered"}, status_code=422)
    user = add_user(body["email"], body.get("password"))
    user["user_metadata"] = body.get("user_metadata") or {}
    return JSONResponse({"id": user["id"], "email": user["email"]})


@app.get("/auth/v1/admin/users")
def admin_list(request: Request) -> Response:
    if not _is_service(request):
        return JSONResponse({"msg": "forbidden"}, status_code=403)
    return JSONResponse({"users": [{"id": u["id"], "email": u["email"]} for u in USERS.values()]})


@app.put("/auth/v1/admin/users/{user_id}")
async def admin_update(user_id: str, request: Request) -> Response:
    if not _is_service(request):
        return JSONResponse({"msg": "forbidden"}, status_code=403)
    user = USERS.get(user_id)
    if user is None:
        return JSONResponse({"msg": "not found"}, status_code=404)
    body = await request.json()
    if "password" in body:
        user["password"] = body["password"]
    if "email" in body:
        user["email"] = body["email"]
    if "ban_duration" in body:
        user["banned"] = body["ban_duration"] != "none"
    if "user_metadata" in body:
        user["user_metadata"] = body["user_metadata"]
    return JSONResponse({"id": user["id"], "email": user["email"]})


@app.post("/auth/v1/invite")
async def invite(request: Request, redirect_to: str = "") -> Response:
    if not _is_service(request):
        return JSONResponse({"msg": "forbidden"}, status_code=403)
    body = await request.json()
    if find_user(body["email"]):
        return JSONResponse({"error_code": "email_exists"}, status_code=422)
    user = add_user(body["email"], None)
    OUTBOX.append({"type": "invite", "email": user["email"], "redirect_to": redirect_to,
                   "token": issue_token(user, method="invite")})
    return JSONResponse({"id": user["id"], "email": user["email"]})


@app.get("/auth/v1/.well-known/jwks.json")
def jwks() -> dict:
    return {"keys": []}


@app.post("/storage/v1/object/sign/{bucket}")
async def sign_many(bucket: str, request: Request) -> Response:
    if not _is_service(request):
        return JSONResponse({"msg": "forbidden"}, status_code=403)
    body = await request.json()
    return JSONResponse([{"path": p, "signedURL": f"/object/sign/{bucket}/{p}?token=mock", "error": None}
                         if (bucket, p) in OBJECTS else {"path": p, "signedURL": None, "error": "not found"}
                         for p in body.get("paths", [])])


@app.get("/storage/v1/object/sign/{bucket}/{path:path}")
def signed_get(bucket: str, path: str) -> Response:
    obj = OBJECTS.get((bucket, path))
    if obj is None:
        return JSONResponse({"msg": "not found"}, status_code=404)
    return Response(obj[0], media_type=obj[1])


@app.get("/storage/v1/object/authenticated/{bucket}/{path:path}")
def download(bucket: str, path: str, request: Request) -> Response:
    if not _is_service(request):
        return JSONResponse({"msg": "forbidden"}, status_code=403)
    obj = OBJECTS.get((bucket, path))
    if obj is None:
        return JSONResponse({"msg": "not found"}, status_code=404)
    return Response(obj[0], media_type=obj[1])


@app.post("/storage/v1/object/{bucket}/{path:path}")
async def upload(bucket: str, path: str, request: Request) -> Response:
    if not _is_service(request):
        return JSONResponse({"msg": "forbidden"}, status_code=403)
    if (bucket, path) in OBJECTS:
        return JSONResponse({"msg": "exists"}, status_code=409)
    OBJECTS[(bucket, path)] = (await request.body(), request.headers.get("content-type", "application/octet-stream"))
    return JSONResponse({"Key": f"{bucket}/{path}"})


@app.delete("/storage/v1/object/{bucket}")
async def remove(bucket: str, request: Request) -> Response:
    if not _is_service(request):
        return JSONResponse({"msg": "forbidden"}, status_code=403)
    body = await request.json()
    for p in body.get("prefixes", []):
        OBJECTS.pop((bucket, p), None)
    return JSONResponse([])
