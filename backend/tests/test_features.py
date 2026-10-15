"""Notes encryption, reports, uploads, devices, maintenance, team, privacy, audit and device ingestion."""

import io
import json
import secrets
import time

from PIL import Image

from app.security.crypto import sign_device_payload
from tests import mock_supabase as mock
from tests.helpers import first_patient, login_as, make_user, sql


def test_notes_are_encrypted_at_rest(client, auth):
    patient = first_patient(client, auth("nurse"), "B02")
    text = "Patient reports chest tightness at 03:10"
    r = client.post(f"/patients/{patient['id']}/notes", json={"category": "nursing", "body": text}, headers=auth("nurse"))
    assert r.status_code == 201
    stored = sql("select body_encrypted from public.notes where id = %s", (r.json()["id"],))[0]["body_encrypted"]
    assert stored.startswith("v1:") and text not in stored
    notes = client.get(f"/patients/{patient['id']}/notes", headers=auth("physician")).json()["items"]
    assert notes[0]["body"] == text and notes[0]["author"] == "Nora Bennett"
    logs = sql("select details::text as d from public.audit_log where action = 'note.create' order by id desc limit 1")
    assert text not in logs[0]["d"]  # audit records never contain clinical free text


def test_csv_report_neutralises_formulas(client, auth):
    patient = first_patient(client, auth("nurse"), "B03")
    sql("update public.patients set last_name = '=HYPERLINK(\"http://x\")' where id = %s", (patient["id"],))
    try:
        r = client.post("/reports", json={"kind": "shift_summary", "period_hours": 2}, headers=auth("nurse"))
        csv_text = client.get(f"/reports/{r.json()['id']}/download", headers=auth("nurse")).content.decode("utf-8-sig")
        assert "'=HYPERLINK" in csv_text
    finally:
        sql("update public.patients set last_name = 'Fernandes' where id = %s", (patient["id"],))


def test_deidentified_report_hides_identity_and_respects_restriction(client, auth):
    patient = first_patient(client, auth("nurse"), "B05")
    assert client.put(f"/patients/{patient['id']}/restriction", json={"restricted": True},
                      headers=auth("admin", aal2=True)).status_code == 200
    r = client.post("/reports", json={"kind": "shift_summary", "period_hours": 2, "deidentified": True},
                    headers=auth("physician"))
    csv_text = client.get(f"/reports/{r.json()['id']}/download", headers=auth("physician")).content.decode("utf-8-sig")
    assert "Ellison" not in csv_text and "ACM-1042" not in csv_text and "PA-" in csv_text
    assert r.json()["row_count"] == 11  # restricted patient excluded from secondary use
    client.put(f"/patients/{patient['id']}/restriction", json={"restricted": False}, headers=auth("admin", aal2=True))


def test_report_integrity_is_verified_on_download(client, auth):
    r = client.post("/reports", json={"kind": "device_maintenance"}, headers=auth("biomed"))
    report = r.json()
    path = f"{report['id']}.csv"
    mock.OBJECTS[("reports", path)] = (b"monitor\r\nTAMPERED\r\n", "text/csv")
    d = client.get(f"/reports/{report['id']}/download", headers=auth("biomed"))
    assert d.status_code == 409 and d.json()["error"]["code"] == "integrity_error"


def _png(size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (20, 40, 90)).save(buf, format="PNG")
    return buf.getvalue()


def test_avatar_upload_is_validated_and_reencoded(client, auth):
    ok = client.post("/me/avatar", files={"file": ("me.png", _png(), "image/png")}, headers=auth("nurse"))
    assert ok.status_code == 200 and ok.json()["avatar_url"]
    fake = client.post("/me/avatar", files={"file": ("x.png", b"<script>alert(1)</script>", "image/png")},
                       headers=auth("nurse"))
    assert fake.status_code == 400
    polyglot = client.post("/me/avatar", files={"file": ("x.png", b"\x89PNG\r\n\x1a\n" + b"<?php echo 1; ?>" * 10,
                                                          "image/png")}, headers=auth("nurse"))
    assert polyglot.status_code == 400
    big = client.post("/me/avatar", files={"file": ("x.png", b"\x89PNG\r\n\x1a\n" + b"0" * 2_200_000, "image/png")},
                      headers=auth("nurse"))
    assert big.status_code == 413
    path = sql("select avatar_path from public.profiles where email like 'nora.bennett%%'")[0]["avatar_path"]
    stored = mock.OBJECTS[("avatars", path)][0]
    assert stored.startswith(b"\x89PNG") and path.endswith(".png")


def test_monitor_assignment_rules(client, auth):
    assert client.post("/devices/MON-10/assign", json={"bed_id": "B01"}, headers=auth("nurse")).status_code == 409
    r = client.post("/devices/MON-10/assign", json={"bed_id": "B10"}, headers=auth("nurse"))
    assert r.status_code == 200, r.text
    assert client.post("/devices/MON-10/assign", json={"bed_id": "B11"}, headers=auth("nurse")).status_code == 409
    assert client.post("/devices/MON-10/assign", json={"bed_id": "../B1"}, headers=auth("nurse")).status_code == 422
    assert client.post("/devices/MON-10/unassign", headers=auth("physician")).status_code == 403
    assert client.post("/devices/MON-10/unassign", headers=auth("biomed")).status_code == 200
    history = client.get("/devices/MON-10", headers=auth("biomed")).json()["assignments"]
    assert history[0]["bed_id"] == "B10" and history[0]["unassigned_at"] is not None


def test_maintenance_lifecycle(client, auth):
    nurse_report = client.post("/devices/MON-01/maintenance", json={"type": "issue_report", "description": "Screen flickers"},
                               headers=auth("nurse"))
    assert nurse_report.status_code == 201
    assert client.post("/devices/MON-01/maintenance", json={"type": "repair", "description": "x"},
                       headers=auth("nurse")).status_code == 403
    ticket = nurse_report.json()["id"]
    assert client.patch(f"/maintenance/{ticket}", json={"status": "completed"}, headers=auth("biomed")).status_code == 422
    done = client.patch(f"/maintenance/{ticket}", json={"status": "completed", "resolution": "Replaced display cable"},
                        headers=auth("biomed"))
    assert done.status_code == 200
    assert client.patch(f"/maintenance/{ticket}", json={"status": "open"}, headers=auth("biomed")).status_code == 409


def test_team_invite_role_change_and_deactivation(client, auth):
    admin = auth("admin", aal2=True)
    r = client.post("/team/invite", json={"email": "new.nurse@acme-clinical.example", "full_name": "Jamie Park",
                                         "role": "nurse"}, headers=admin)
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]
    invite = next(m for m in mock.OUTBOX if m["email"] == "new.nurse@acme-clinical.example")
    assert invite["redirect_to"].endswith("/accept-invite")
    assert client.post("/auth/reset-password", json={"access_token": invite["token"],
                                                     "new_password": "Jamie-Park-2026!"}).status_code == 200
    headers = login_as(client, {"email": "new.nurse@acme-clinical.example", "password": "Jamie-Park-2026!"})
    assert client.patch(f"/team/{user_id}", json={"role": "physician"}, headers=admin).status_code == 200
    assert client.get("/me", headers=headers).status_code == 401  # role change forces re-authentication
    assert client.patch(f"/team/{user_id}", json={"active": False}, headers=admin).status_code == 200
    r = client.post("/auth/login", json={"email": "new.nurse@acme-clinical.example", "password": "Jamie-Park-2026!"})
    assert r.status_code == 401
    assert client.post("/team/invite", json={"email": "new.nurse@acme-clinical.example", "full_name": "Jamie Park",
                                             "role": "nurse"}, headers=admin).status_code == 409


def test_privacy_rights(client, auth):
    user = make_user("nurse", name="Robin Vale")
    headers = login_as(client, user)
    me = client.get("/me", headers=headers).json()
    assert me["consent"]["required"] is True
    assert client.post("/me/consent", json={"version": "2026-10"}, headers=headers).json()["accepted"] is True
    export = client.get("/me/export", headers=headers)
    assert export.status_code == 200 and "attachment" in export.headers["content-disposition"]
    assert export.json()["profile"]["email"] == user["email"]
    assert client.post("/me/privacy-requests", json={"kind": "deletion"}, headers=headers).status_code == 200
    admin = auth("admin", aal2=True)
    requests = client.get("/team/privacy-requests", headers=admin).json()["items"]
    assert any(r["user_id"] == user["id"] and r["status"] == "pending" for r in requests)
    assert client.post(f"/team/{user['id']}/anonymize", headers=admin).status_code == 200
    row = sql("select full_name, email, phone, active from public.profiles where id = %s", (user["id"],))[0]
    assert row["full_name"] == "Former staff member" and row["active"] is False and "anonymized.invalid" in row["email"]


def test_audit_chain_detects_tampering(client, auth):
    admin = auth("admin", aal2=True)
    assert client.get("/admin/audit/verify", headers=admin).json()["valid"] is True
    target = sql("select id, action from public.audit_log order by id desc offset 3 limit 1")[0]
    sql("update public.audit_log set action = 'tampered' where id = %s", (target["id"],))
    try:
        result = client.get("/admin/audit/verify", headers=admin).json()
        assert result["valid"] is False and result["broken_at"] == target["id"]
    finally:
        sql("update public.audit_log set action = %s where id = %s", (target["action"], target["id"]))


def _signed(monitor: str, body: dict, ts: int | None = None, nonce: str | None = None) -> tuple[bytes, dict]:
    raw = json.dumps(body).encode()
    ts_s = str(ts or int(time.time()))
    nonce = nonce or secrets.token_urlsafe(18)
    return raw, {"Content-Type": "application/json", "X-Device-Id": monitor, "X-Timestamp": ts_s, "X-Nonce": nonce,
                 "X-Signature": sign_device_payload(monitor, ts_s, nonce, raw)}


def test_device_ingestion_requires_valid_signature(client):
    body, headers = _signed("MON-01", {"heart_rate": 77, "spo2": 98})
    assert client.post("/devices/ingest", content=body, headers=headers).status_code == 202
    assert client.post("/devices/ingest", content=body, headers=headers).status_code == 409  # replay
    body2, headers2 = _signed("MON-01", {"heart_rate": 77})
    headers2["X-Device-Id"] = "MON-02"  # signature made for another device
    assert client.post("/devices/ingest", content=body2, headers=headers2).status_code == 401
    old, old_headers = _signed("MON-01", {"heart_rate": 77}, ts=int(time.time()) - 3600)
    assert client.post("/devices/ingest", content=old, headers=old_headers).status_code == 401


def test_data_retention_purge(client, auth):
    sql("insert into public.vital_readings (monitor_id, tick, recorded_at, heart_rate) "
        "values ('MON-01', 0, now() - interval '30 days', 70)")
    sql("select public.purge_expired_data(interval '7 days')")
    assert not sql("select 1 from public.vital_readings where recorded_at < now() - interval '20 days'")
