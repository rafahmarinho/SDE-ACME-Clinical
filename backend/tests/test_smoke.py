from tests.conftest import login


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.headers["x-content-type-options"] == "nosniff"


def test_login_and_overview(client, seeded):
    headers = login(client, seeded, "nurse")
    r = client.get("/ward/overview", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["beds"]) == 12
    assert body["kpis"]["patients"] == 12
