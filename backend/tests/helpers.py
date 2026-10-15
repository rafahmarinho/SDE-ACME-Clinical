"""Shared helpers for tests."""

import uuid

from app.db import transaction
from tests import mock_supabase as mock
from tests.conftest import DEMO_PASSWORD


def make_user(role: str, password: str = DEMO_PASSWORD, name: str = "Test User") -> dict:
    email = f"user-{uuid.uuid4().hex[:10]}@acme-clinical.example"
    user = mock.add_user(email, password)
    with transaction() as conn:
        conn.execute("insert into public.profiles (id, email, full_name, role) values (%s, %s, %s, %s)",
                     (user["id"], email, name, role))
    return {"id": user["id"], "email": email, "password": password}


def login_as(client, user: dict) -> dict[str, str]:
    r = client.post("/auth/login", json={"email": user["email"], "password": user["password"]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def sql(query: str, params=None):
    with transaction() as conn:
        cur = conn.execute(query, params or ())
        return cur.fetchall() if cur.description else None


def first_patient(client, headers, bed: str = "B01") -> dict:
    r = client.post("/patients/search", json={"q": bed}, headers=headers)
    assert r.status_code == 200, r.text
    return next(p for p in r.json()["items"] if p["bed_id"] == bed)
