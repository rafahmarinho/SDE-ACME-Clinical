"""Role-based access control, object-level authorization and break-glass access."""

import uuid

import pytest

from app.security import authz
from tests.helpers import first_patient, login_as, make_user, sql


@pytest.mark.parametrize(
    ("role", "method", "path", "expected"),
    [
        ("nurse", "get", "/team", 403),
        ("physician", "get", "/admin/audit", 403),
        ("biomed", "post", "/patients/search", 403),
        ("nurse", "get", "/simulation/state", 403),
        ("physician", "post", "/simulation/reset", 403),
        ("biomed", "get", "/thresholds/defaults", 403),
        ("nurse", "get", "/ward/overview", 200),
        ("biomed", "get", "/devices", 200),
        ("biomed", "get", "/simulation/state", 200),
    ],
)
def test_function_level_authorization(client, auth, role, method, path, expected):
    kwargs = {"json": {"confirm": "RESET"}} if path == "/simulation/reset" else {}
    if path == "/patients/search":
        kwargs = {"json": {}}
    r = getattr(client, method)(path, headers=auth(role), **kwargs)
    assert r.status_code == expected, r.text


def test_permission_matrix_denies_unknown_permissions():
    assert authz.allowed("admin", "does:not:exist") is False
    assert authz.allowed(None, "ward:view") is False


def test_authorization_denials_are_audited(client, auth):
    client.get("/team", headers=auth("nurse"))
    rows = sql("select action, outcome from public.audit_log where action = 'authz.denied' order by id desc limit 1")
    assert rows and rows[0]["outcome"] == "denied"


def test_biomed_ward_view_hides_patient_identity(client, auth):
    beds = client.get("/ward/overview", headers=auth("biomed")).json()["beds"]
    assert all(b["first_name"] is None and b["heart_rate"] is None for b in beds)
    assert any(b["occupied"] for b in beds)
    nurse_beds = client.get("/ward/overview", headers=auth("nurse")).json()["beds"]
    assert any(b["first_name"] for b in nurse_beds)


def test_unknown_patient_returns_404(client, auth):
    r = client.get(f"/patients/{uuid.uuid4()}", headers=auth("nurse"))
    assert r.status_code == 404


def test_break_glass_grants_time_limited_patient_access(client, auth):
    tech = make_user("biomed", name="Break Glass")
    headers = login_as(client, tech)
    patient = first_patient(client, auth("nurse"), "B04")
    assert client.get(f"/patients/{patient['id']}", headers=headers).status_code == 403
    short = client.post(f"/patients/{patient['id']}/emergency-access", json={"reason": "too short"}, headers=headers)
    assert short.status_code == 422
    grant = client.post(f"/patients/{patient['id']}/emergency-access",
                        json={"reason": "Monitor alarm unresolved, no nurse available at bedside"}, headers=headers)
    assert grant.status_code == 201
    assert client.get(f"/patients/{patient['id']}", headers=headers).status_code == 200
    other = first_patient(client, auth("nurse"), "B05")
    assert client.get(f"/patients/{other['id']}", headers=headers).status_code == 403  # only that patient
    sql("update public.emergency_access set expires_at = now() - interval '1 minute' where user_id = %s", (tech["id"],))
    assert client.get(f"/patients/{patient['id']}", headers=headers).status_code == 403
    outbox = sql("select channel from public.integration_outbox where subject = 'Emergency access granted'")
    assert outbox


def test_only_physicians_edit_patient_thresholds(client, auth):
    patient = first_patient(client, auth("nurse"), "B02")
    body = {"items": [{"parameter": "heart_rate", "low": 45, "high": 125}]}
    assert client.put(f"/patients/{patient['id']}/thresholds", json=body, headers=auth("nurse")).status_code == 403
    r = client.put(f"/patients/{patient['id']}/thresholds", json=body, headers=auth("physician"))
    assert r.status_code == 200
    assert r.json()["thresholds"]["heart_rate"]["high"] == 125


def test_admin_cannot_write_clinical_notes(client, auth):
    patient = first_patient(client, auth("nurse"))
    r = client.post(f"/patients/{patient['id']}/notes", json={"category": "nursing", "body": "x"},
                    headers=auth("admin", aal2=True))
    assert r.status_code == 403


def test_nurse_cannot_write_physician_notes(client, auth):
    patient = first_patient(client, auth("nurse"))
    r = client.post(f"/patients/{patient['id']}/notes", json={"category": "physician", "body": "Order"},
                    headers=auth("nurse"))
    assert r.status_code == 403


def test_reports_are_filtered_by_role(client, auth):
    created = client.post("/reports", json={"kind": "shift_summary", "period_hours": 1}, headers=auth("nurse"))
    assert created.status_code == 201
    report_id = created.json()["id"]
    assert client.get(f"/reports/{report_id}", headers=auth("biomed")).status_code == 403
    kinds = client.get("/reports", headers=auth("biomed")).json()["kinds"]
    assert kinds == ["device_maintenance"]


def test_admin_cannot_change_own_role(client, auth, seeded):
    r = client.patch(f"/team/{seeded['admin']['id']}", json={"role": "nurse"}, headers=auth("admin", aal2=True))
    assert r.status_code == 403
