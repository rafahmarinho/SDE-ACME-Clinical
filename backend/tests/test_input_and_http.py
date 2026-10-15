"""Input validation, injection resistance and HTTP-level hardening."""

import pytest

from tests.helpers import first_patient


@pytest.mark.parametrize("payload", ["' OR '1'='1", "x'; drop table public.patients; --", "%' union select null --"])
def test_search_is_not_sql_injectable(client, auth, payload):
    r = client.post("/patients/search", json={"q": payload, "status": "all"}, headers=auth("nurse"))
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert client.post("/patients/search", json={}, headers=auth("nurse")).json()["total"] == 12


def test_unknown_fields_are_rejected(client, auth):
    r = client.post("/patients/search", json={"q": "", "role": "admin"}, headers=auth("nurse"))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


def test_sort_must_come_from_allowlist(client, auth):
    r = client.post("/patients/search", json={"sort": "p.mrn; select 1"}, headers=auth("nurse"))
    assert r.status_code == 422


def test_control_and_invisible_characters_are_refused(client, auth):
    r = client.post("/patients/search", json={"q": "Ell‮ison"}, headers=auth("nurse"))
    assert r.status_code == 422
    r = client.patch("/me", json={"full_name": "Nora\x00Bennett"}, headers=auth("nurse"))
    assert r.status_code == 422


def test_homoglyph_names_are_refused(client, auth):
    r = client.patch("/me", json={"full_name": "Nоra Bennett"}, headers=auth("nurse"))  # Cyrillic 'о'
    assert r.status_code == 422


def test_overlong_input_is_refused(client, auth):
    patient = first_patient(client, auth("nurse"))
    r = client.post(f"/patients/{patient['id']}/notes", json={"category": "nursing", "body": "a" * 4001},
                    headers=auth("nurse"))
    assert r.status_code == 422


def test_request_body_size_is_limited(client, auth):
    r = client.post("/patients/search", content=b"{" + b" " * 1_100_000 + b"}", headers={
        **auth("nurse"), "Content-Type": "application/json"})
    assert r.status_code == 413


def test_duplicate_query_parameters_are_refused(client, auth):
    r = client.get("/alarms?state=active&state=all", headers=auth("nurse"))
    assert r.status_code == 400


def test_http_verb_tampering(client, auth):
    assert client.request("TRACE", "/health").status_code == 405
    assert client.delete("/ward/overview", headers=auth("nurse")).status_code == 405
    assert client.put("/alarms", headers=auth("nurse")).status_code == 405


def test_security_headers_present(client):
    r = client.get("/health")
    for header in ("strict-transport-security", "x-content-type-options", "x-frame-options", "content-security-policy",
                   "referrer-policy", "cache-control", "x-request-id"):
        assert header in r.headers
    assert r.headers["cache-control"] == "no-store"
    assert "server" not in r.headers


def test_cors_allows_only_configured_origin(client):
    ok = client.options("/me", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "access-control-allow-credentials" not in ok.headers
    bad = client.options("/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers


def test_api_docs_disabled_in_production(monkeypatch):
    from app import config
    from app.main import create_app

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("APP_URL", "https://clinical.example.com")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://clinical.example.com")
    monkeypatch.setenv("DATABASE_URL", "postgresql://acme_api:x@db.example.com:6543/postgres?sslmode=require")
    config.get_settings.cache_clear()
    try:
        app = create_app()
        assert app.docs_url is None and app.openapi_url is None
    finally:
        config.get_settings.cache_clear()


def test_production_refuses_unencrypted_database(monkeypatch):
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("APP_URL", "https://clinical.example.com")
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://clinical.example.com")
    monkeypatch.setenv("DATABASE_URL", "postgresql://acme_api:x@db.example.com:6543/postgres")
    with pytest.raises(ValidationError):
        Settings()


def test_errors_do_not_leak_internals(client, auth):
    r = client.get("/patients/not-a-uuid", headers=auth("nurse"))
    assert r.status_code == 422
    body = r.text.lower()
    assert "traceback" not in body and "psycopg" not in body


def test_json_responses_are_objects(client, auth):
    for path in ("/alarms", "/devices", "/reports"):
        assert isinstance(client.get(path, headers=auth("nurse")).json(), dict)


def test_threshold_ranges_are_validated(client, auth):
    body = {"items": [{"parameter": "spo2", "low": 120, "high": None}]}
    assert client.put("/thresholds/defaults", json=body, headers=auth("physician")).status_code == 422
    body = {"items": [{"parameter": "heart_rate", "low": 130, "high": 100}]}
    assert client.put("/thresholds/defaults", json=body, headers=auth("physician")).status_code == 422
