"""Simulator scenarios and the alarm lifecycle (acknowledge never clears an ongoing condition)."""

from tests.helpers import sql


def _set(client, auth, monitor, scenario):
    r = client.put(f"/simulation/monitors/{monitor}/scenario", json={"scenario": scenario}, headers=auth("biomed"))
    assert r.status_code == 200, r.text


def _advance(client, auth, steps):
    r = client.post("/simulation/advance", json={"steps": steps}, headers=auth("nurse"))
    assert r.status_code == 200, r.text
    return r.json()


def _active(monitor, alarm_type):
    return sql("select * from public.alarms where monitor_id = %s and type = %s and state = 'active'", (monitor, alarm_type))


def test_low_spo2_alarm_stays_active_after_acknowledgement(client, auth):
    _set(client, auth, "MON-04", "low_spo2")
    _advance(client, auth, 10)
    alarm = _active("MON-04", "spo2_low")
    assert alarm, "a low saturation alarm should be raised"
    ack = client.post(f"/alarms/{alarm[0]['id']}/acknowledge", json={"note": "Oxygen increased"}, headers=auth("nurse"))
    assert ack.status_code == 200
    assert ack.json()["state"] == "active"
    _advance(client, auth, 2)
    still = _active("MON-04", "spo2_low")
    assert still and still[0]["acknowledged_at"] is not None  # acknowledged, condition still present
    again = client.post(f"/alarms/{alarm[0]['id']}/acknowledge", json={}, headers=auth("nurse"))
    assert again.status_code == 409
    _set(client, auth, "MON-04", "normal")
    _advance(client, auth, 12)
    assert not _active("MON-04", "spo2_low")
    resolved = sql("select state, resolved_at from public.alarms where id = %s", (alarm[0]["id"],))
    assert resolved[0]["state"] == "resolved" and resolved[0]["resolved_at"] is not None


def test_weak_battery_raises_technical_alarm(client, auth):
    _set(client, auth, "MON-06", "weak_battery")
    _advance(client, auth, 45)
    alarm = _active("MON-06", "battery_low")
    assert alarm and alarm[0]["category"] == "technical"
    # Physiological acknowledgement rights do not cover the biomed role, technical ones do.
    r = client.post(f"/alarms/{alarm[0]['id']}/acknowledge", json={}, headers=auth("biomed"))
    assert r.status_code == 200
    _set(client, auth, "MON-06", "normal")


def test_sensor_issue_blanks_saturation_and_raises_alarm(client, auth):
    _set(client, auth, "MON-05", "sensor_issue")
    _advance(client, auth, 3)
    assert _active("MON-05", "sensor_issue")
    latest = sql("select spo2, heart_rate, quality from public.vital_readings where monitor_id = 'MON-05' "
                 "order by id desc limit 1")[0]
    assert latest["quality"] == "artifact"
    assert latest["spo2"] is None or latest["heart_rate"] is None
    _set(client, auth, "MON-05", "normal")
    _advance(client, auth, 2)
    assert not _active("MON-05", "sensor_issue")


def test_lost_connection_is_detected_by_watchdog(client, auth):
    _set(client, auth, "MON-07", "lost_connection")
    before = sql("select count(*) as n from public.vital_readings where monitor_id = 'MON-07'")[0]["n"]
    _advance(client, auth, 3)
    after = sql("select count(*) as n from public.vital_readings where monitor_id = 'MON-07'")[0]["n"]
    assert after == before  # no data while disconnected
    alarm = _active("MON-07", "connection_lost")
    assert alarm and alarm[0]["severity"] == "critical"
    pager = sql("select 1 from public.integration_outbox where channel = 'pager' and subject like %s", ("%Connection lost%",))
    assert pager
    ecg = client.get("/monitors/MON-07/ecg", headers=auth("nurse")).json()
    assert ecg["status"] == "no_signal"
    _set(client, auth, "MON-07", "normal")
    _advance(client, auth, 1)
    assert not _active("MON-07", "connection_lost")


def test_presets_apply_scenarios(client, auth):
    r = client.post("/simulation/presets/network_outage", headers=auth("admin"))
    assert r.status_code == 200
    rows = sql("select id, scenario from public.monitors where id in ('MON-07', 'MON-08', 'MON-01') order by id")
    assert [r["scenario"] for r in rows] == ["normal", "lost_connection", "lost_connection"]
    client.post("/simulation/presets/all_normal", headers=auth("admin"))


def test_ecg_waveform(client, auth):
    r = client.get("/monitors/MON-01/ecg?seconds=4", headers=auth("physician")).json()
    assert r["fs"] == 125 and len(r["samples"]) == 500
    assert max(r["samples"]) > 0.6  # R peaks present


def test_events_inspector(client, auth):
    r = client.get("/simulation/events?kind=scenario_change&limit=5", headers=auth("biomed"))
    assert r.status_code == 200
    assert all(e["kind"] == "scenario_change" for e in r.json()["items"])


def test_reset_requires_admin_mfa_and_confirmation(client, auth):
    assert client.post("/simulation/reset", json={"confirm": "RESET"}, headers=auth("admin")).status_code == 403
    assert client.post("/simulation/reset", json={"confirm": "yes"}, headers=auth("admin", aal2=True)).status_code == 422
    r = client.post("/simulation/reset", json={"confirm": "RESET"}, headers=auth("admin", aal2=True))
    assert r.status_code == 200
    assert sql("select count(*) as n from public.patients")[0]["n"] == 12
    assert sql("select count(*) as n from public.monitors")[0]["n"] == 10
    assert _active("MON-03", "spo2_low")  # demo starts with a desaturation in progress


def test_generation_is_deterministic():
    from app.services import simulation

    monitor = {"id": "MON-01", "scenario": "normal", "battery_pct": 100, "sim_state": {}}
    a, _ = simulation._generate(monitor, {"hr": 80}, 10, 4242)
    b, _ = simulation._generate(monitor, {"hr": 80}, 10, 4242)
    assert a == b
