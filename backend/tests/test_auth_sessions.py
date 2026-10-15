"""Authentication, password management and session security."""

import time

import jwt

from tests import mock_supabase as mock
from tests.conftest import DEMO_PASSWORD
from tests.helpers import login_as, make_user, sql


def test_requests_without_token_are_rejected(client):
    r = client.get("/ward/overview")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "not_authenticated"


def test_tampered_token_is_rejected(client, seeded):
    headers = login_as(client, make_user("nurse"))
    token = headers["Authorization"][7:]
    claims = jwt.decode(token, options={"verify_signature": False})
    claims["sub"] = seeded["admin"]["id"]
    forged = jwt.encode(claims, "wrong-secret-wrong-secret-wrong-secret!!", algorithm="HS256")
    r = client.get("/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_token"


def test_token_not_created_through_api_login_is_rejected(client, seeded):
    """A session obtained directly from the identity provider bypasses throttling, so the API refuses it."""
    user = mock.find_user(seeded["nurse"]["email"])
    direct = mock.issue_token(user)
    r = client.get("/me", headers={"Authorization": f"Bearer {direct}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "session_revoked"


def test_failed_logins_use_one_generic_message_and_delay(client):
    user = make_user("nurse")
    t0 = time.perf_counter()
    wrong = client.post("/auth/login", json={"email": user["email"], "password": "Wrong-password-1!"})
    elapsed = time.perf_counter() - t0
    unknown = client.post("/auth/login", json={"email": "nobody-here@acme-clinical.example", "password": "Xx-123456789!"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"]["message"] == unknown.json()["error"]["message"] == "Invalid e-mail or password."
    assert elapsed >= 0.25  # random failure delay


def test_account_lockout_after_repeated_failures(client):
    user = make_user("nurse")
    for _ in range(5):
        client.post("/auth/login", json={"email": user["email"], "password": "Wrong-password-1!"})
    r = client.post("/auth/login", json={"email": user["email"], "password": user["password"]})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "account_locked"
    sql("delete from public.auth_throttle")
    assert client.post("/auth/login", json={"email": user["email"], "password": user["password"]}).status_code == 200


def test_login_records_previous_sign_in(client):
    user = make_user("physician")
    login_as(client, user)
    r = client.post("/auth/login", json={"email": user["email"], "password": user["password"]})
    assert r.json()["previous_sign_in"]["at"] is not None
    me = client.get("/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).json()
    assert me["previous_sign_in"]["at"] is not None


def test_logout_revokes_the_session_immediately(client):
    headers = login_as(client, make_user("nurse"))
    assert client.get("/me", headers=headers).status_code == 200
    assert client.post("/auth/logout", headers=headers).status_code == 200
    r = client.get("/me", headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "session_revoked"


def test_idle_timeout_is_enforced_server_side(client):
    user = make_user("nurse")
    headers = login_as(client, user)
    sql("update public.user_sessions set last_seen_at = now() - interval '16 minutes' where user_id = %s", (user["id"],))
    r = client.get("/me", headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "session_expired"


def test_heartbeat_keeps_an_active_session_alive(client):
    user = make_user("nurse")
    headers = login_as(client, user)
    sql("update public.user_sessions set last_seen_at = now() - interval '10 minutes' where user_id = %s", (user["id"],))
    assert client.post("/auth/heartbeat", headers=headers).status_code == 200
    assert client.get("/me", headers=headers).status_code == 200


def test_absolute_timeout_is_enforced(client):
    user = make_user("nurse")
    headers = login_as(client, user)
    sql("update public.user_sessions set expires_at = now() - interval '1 minute' where user_id = %s", (user["id"],))
    r = client.get("/me", headers=headers)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "session_expired"


def test_concurrent_sessions_are_limited(client):
    user = make_user("nurse")
    first = login_as(client, user)
    for _ in range(3):
        login_as(client, user)
    assert client.get("/me", headers=first).status_code == 401  # oldest session revoked (limit 3)


def test_session_ids_differ_between_logins(client):
    user = make_user("nurse")
    a = jwt.decode(login_as(client, user)["Authorization"][7:], options={"verify_signature": False})
    b = jwt.decode(login_as(client, user)["Authorization"][7:], options={"verify_signature": False})
    assert a["session_id"] != b["session_id"]


def test_inactive_account_cannot_sign_in(client):
    user = make_user("nurse")
    sql("update public.profiles set active = false where id = %s", (user["id"],))
    r = client.post("/auth/login", json={"email": user["email"], "password": user["password"]})
    assert r.status_code == 401
    assert r.json()["error"]["message"] == "Invalid e-mail or password."


def test_mfa_enrolled_user_needs_aal2(client):
    user = make_user("physician")
    mock.USERS[user["id"]]["factors"] = [{"id": "f1", "status": "verified", "factor_type": "totp"}]
    r = client.post("/auth/login", json={"email": user["email"], "password": user["password"]})
    body = r.json()
    assert body["mfa_required"] is True
    aal1 = {"Authorization": f"Bearer {body['access_token']}"}
    assert client.get("/me", headers=aal1).json()["error"]["code"] == "mfa_required"
    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    aal2 = {"Authorization": f"Bearer {mock.issue_token(mock.USERS[user['id']], claims['session_id'], aal='aal2')}"}
    assert client.get("/me", headers=aal2).status_code == 200


def test_admin_actions_require_mfa(client, auth):
    r = client.get("/team", headers=auth("admin"))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "mfa_required_admin"
    assert client.get("/team", headers=auth("admin", aal2=True)).status_code == 200


def test_change_password_requires_current_password_and_policy(client):
    user = make_user("nurse")
    headers = login_as(client, user)
    wrong = client.post("/me/password", json={"current_password": "Not-the-password1!", "new_password": "N3w-Strong-Pass!"},
                        headers=headers)
    assert wrong.status_code == 400
    weak = client.post("/me/password", json={"current_password": user["password"], "new_password": "short"}, headers=headers)
    assert weak.status_code == 422
    ok = client.post("/me/password", json={"current_password": user["password"], "new_password": "N3w-Strong-Pass!x"},
                     headers=headers)
    assert ok.status_code == 200
    assert mock.USERS[user["id"]]["password"] == "N3w-Strong-Pass!x"


def test_password_recovery_does_not_reveal_accounts(client, seeded):
    known = client.post("/auth/recover", json={"email": seeded["nurse"]["email"]})
    unknown = client.post("/auth/recover", json={"email": "ghost@acme-clinical.example"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


def test_password_reset_with_recovery_link(client):
    user = make_user("nurse")
    old_session = login_as(client, user)
    client.post("/auth/recover", json={"email": user["email"]})
    link = next(m for m in reversed(mock.OUTBOX) if m["email"] == user["email"])
    assert link["redirect_to"] == "http://localhost:5173/reset-password"
    r = client.post("/auth/reset-password", json={"access_token": link["token"], "new_password": "Recovered-Pass-2026!"})
    assert r.status_code == 200, r.text
    assert mock.USERS[user["id"]]["password"] == "Recovered-Pass-2026!"
    assert client.get("/me", headers=old_session).status_code == 401  # all sessions revoked


def test_password_reset_rejects_normal_session_tokens(client):
    user = make_user("nurse")
    token = login_as(client, user)["Authorization"][7:]
    r = client.post("/auth/reset-password", json={"access_token": token, "new_password": "Another-Pass-2026!"})
    assert r.status_code == 400


def test_password_policy_endpoint(client):
    policy = client.get("/auth/policy").json()
    assert policy["password"]["min_length"] >= 12


def test_demo_password_not_hardcoded():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "app"
    for path in root.rglob("*.py"):
        assert DEMO_PASSWORD not in path.read_text(encoding="utf-8")
