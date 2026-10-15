"""Test harness: a real PostgreSQL 17 (PGlite) with the production migration, plus a mock Supabase."""

import base64
import os
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
DEMO_PASSWORD = "Ward4B-Demo!2026"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


PORT = _free_port()
os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": f"postgresql://postgres:postgres@127.0.0.1:{PORT}/postgres?sslmode=disable",
    "DB_POOL_MAX_SIZE": "1",
    "SUPABASE_URL": "http://supabase.mock",
    "SUPABASE_ANON_KEY": "sb_publishable_test_anon_key_0000",
    "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_test_service_key_00000",
    "SUPABASE_JWT_SECRET": "test-jwt-secret-with-at-least-32-characters!!",
    "DATA_ENCRYPTION_KEY": _key(),
    "AUDIT_HMAC_KEY": _key(),
    "PSEUDONYM_KEY": _key(),
    "DEVICE_MASTER_KEY": _key(),
    "APP_URL": "http://localhost:5173",
    "ALLOWED_ORIGINS": "http://localhost:5173",
    "REQUIRE_ADMIN_MFA": "true",
    "LOGIN_IP_LIMIT_PER_5MIN": "5000",
})
sys.path.insert(0, str(ROOT))

from tests.pgtools import apply_schema, start_pglite  # noqa: E402


@pytest.fixture(scope="session")
def pglite():
    proc = start_pglite(PORT)
    try:
        apply_schema(os.environ["DATABASE_URL"])
        yield
    finally:
        from app.db import close_pool

        close_pool()
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def mock_supabase():
    from fastapi.testclient import TestClient

    from app.services import supabase
    from tests import mock_supabase as mock

    mock_client = TestClient(mock.app, base_url=os.environ["SUPABASE_URL"])

    def handler(request: httpx.Request) -> httpx.Response:
        resp = mock_client.request(request.method, str(request.url), content=request.content,
                                   headers=dict(request.headers))
        return httpx.Response(resp.status_code, headers=resp.headers, content=resp.content)

    supabase.reset_client()
    supabase.transport = httpx.MockTransport(handler)
    yield mock
    supabase.reset_client()


@pytest.fixture(scope="session")
def seeded(pglite, mock_supabase):
    from app.db import transaction
    from app.services import seed

    staff = {}
    with transaction() as conn:
        for s in seed.DEMO_STAFF:
            email = s["full_name"].lower().replace(" ", ".") + "@acme-clinical.example"
            user = mock_supabase.add_user(email, DEMO_PASSWORD)
            conn.execute(
                "insert into public.profiles (id, email, full_name, role, job_title) values (%s, %s, %s, %s, %s)",
                (user["id"], email, s["full_name"], s["role"], s["job_title"]),
            )
            staff[s["role"]] = {"id": user["id"], "email": email, "name": s["full_name"]}
        seed.reset_demo_data(conn, history_ticks=40)
    return staff


@pytest.fixture(scope="session")
def client(seeded):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app, base_url="http://testserver", raise_server_exceptions=False) as c:
        yield c


def login(client, staff, role: str, aal2: bool = False) -> dict[str, str]:
    resp = client.post("/auth/login", json={"email": staff[role]["email"], "password": DEMO_PASSWORD})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    if aal2:
        import jwt

        from tests import mock_supabase as mock

        claims = jwt.decode(token, options={"verify_signature": False})
        user = mock.USERS[claims["sub"]]
        token = mock.issue_token(user, claims["session_id"], aal="aal2")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(scope="session")
def auth(client, seeded):
    cache: dict[tuple[str, bool], dict[str, str]] = {}

    def get(role: str, aal2: bool = False) -> dict[str, str]:
        if (role, aal2) not in cache:
            cache[(role, aal2)] = login(client, seeded, role, aal2)
        return cache[(role, aal2)]

    return get


@pytest.fixture
def db():
    from app.db import transaction

    with transaction() as conn:
        yield conn
