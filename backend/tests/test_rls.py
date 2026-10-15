"""Row Level Security as seen by the browser (Supabase Realtime / PostgREST use the 'authenticated' role)."""

import json

import jwt
import psycopg
import pytest

from app.db import transaction
from tests.helpers import login_as, make_user


def _claims(headers: dict) -> dict:
    return jwt.decode(headers["Authorization"][7:], options={"verify_signature": False})


def _count_as(claims: dict | None, table: str, role: str = "authenticated") -> int:
    with transaction() as conn:
        conn.execute(f"set local role {role}")
        conn.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps(claims or {}),))
        return conn.execute(f"select count(*) as n from public.{table}").fetchone()["n"]


def test_clinical_staff_can_read_ward_data(client):
    claims = _claims(login_as(client, make_user("nurse")))
    assert _count_as(claims, "patients") == 12
    assert _count_as(claims, "monitors") == 10


def test_technical_role_cannot_read_patients(client):
    claims = _claims(login_as(client, make_user("biomed")))
    assert _count_as(claims, "patients") == 0
    assert _count_as(claims, "vital_readings") == 0
    assert _count_as(claims, "monitors") == 10


def test_revoked_or_foreign_sessions_see_nothing(client):
    user = make_user("nurse")
    headers = login_as(client, user)
    claims = _claims(headers)
    client.post("/auth/logout", headers=headers)
    assert _count_as(claims, "patients") == 0
    assert _count_as({"sub": user["id"], "session_id": "00000000-0000-0000-0000-000000000000"}, "patients") == 0


def test_sensitive_tables_are_never_exposed_to_the_browser(client):
    claims = _claims(login_as(client, make_user("nurse")))
    for table in ("audit_log", "user_sessions", "auth_throttle", "reports", "emergency_access"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            _count_as(claims, table)


def test_anonymous_role_has_no_access():
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        _count_as(None, "patients", role="anon")


def test_profiles_only_expose_own_row(client):
    claims = _claims(login_as(client, make_user("physician")))
    assert _count_as(claims, "profiles") == 1
