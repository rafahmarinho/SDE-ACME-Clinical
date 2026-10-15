"""Patient-monitor simulator and alarm engine.

* Each tick produces one reading per active, bed-assigned monitor. Values are deterministic for a
  given (seed, tick, monitor) so a reset reproduces the same demo.
* Scenarios: normal, low_spo2, weak_battery, sensor_issue, lost_connection.
* Alarm lifecycle: a condition raises an alarm once (one active alarm per monitor + type). The
  alarm stays ACTIVE while the condition persists - acknowledging only records who saw it - and is
  RESOLVED by the engine when the condition is no longer observed. Parameters without valid data
  (probe off, connection lost) are neither raised nor resolved: their state is unknown.
"""

import math
import random
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

SCENARIOS = ("normal", "low_spo2", "weak_battery", "sensor_issue", "lost_connection")

SCENARIO_LABELS = {
    "normal": "Normal readings",
    "low_spo2": "Low oxygen saturation",
    "weak_battery": "Weak battery",
    "sensor_issue": "Sensor issue",
    "lost_connection": "Lost connection",
}

PRESETS: dict[str, dict[str, Any]] = {
    "all_normal": {"label": "All normal", "description": "Every monitor reports normal readings.", "monitors": {}},
    "desaturation": {"label": "Desaturation event", "description": "Bed 3 desaturates (SpO2 drops to the low 80s).",
                     "monitors": {"MON-03": "low_spo2"}},
    "battery_round": {"label": "Battery round", "description": "Two monitors run on a failing battery.",
                      "monitors": {"MON-02": "weak_battery", "MON-09": "weak_battery"}},
    "sensor_trouble": {"label": "Sensor trouble", "description": "Bed 5 has an SpO2 probe / ECG lead problem.",
                       "monitors": {"MON-05": "sensor_issue"}},
    "network_outage": {"label": "Network outage", "description": "Beds 7 and 8 stop reporting.",
                       "monitors": {"MON-07": "lost_connection", "MON-08": "lost_connection"}},
    "busy_shift": {"label": "Busy shift", "description": "A mix of clinical and technical problems.",
                   "monitors": {"MON-03": "low_spo2", "MON-05": "sensor_issue", "MON-08": "lost_connection",
                                "MON-09": "weak_battery"}},
}

DEFAULT_THRESHOLDS = {
    "heart_rate": (50, 120),
    "spo2": (90, None),
    "resp_rate": (8, 25),
    "systolic": (90, 160),
    "diastolic": (50, 100),
}

ALARM_LABELS = {
    "hr_high": "Heart rate high",
    "hr_low": "Heart rate low",
    "spo2_low": "SpO2 low",
    "rr_high": "Respiratory rate high",
    "rr_low": "Respiratory rate low",
    "bp_high": "Blood pressure high",
    "bp_low": "Blood pressure low",
    "battery_low": "Battery low",
    "sensor_issue": "Sensor issue",
    "connection_lost": "Connection lost",
}

# Which alarm types can be evaluated from which reading field.
_EVALUATED_BY = {
    "hr_high": "heart_rate", "hr_low": "heart_rate",
    "spo2_low": "spo2",
    "rr_high": "resp_rate", "rr_low": "resp_rate",
    "bp_high": "systolic", "bp_low": "systolic",
}


def _event(conn: psycopg.Connection, tick: int, at: datetime, kind: str, message: str, *,
           monitor_id: str | None = None, patient_id: Any = None, data: dict | None = None, actor_id: Any = None) -> None:
    conn.execute(
        """insert into public.sim_events (tick, occurred_at, kind, monitor_id, patient_id, message, data, actor_id)
           values (%s, %s, %s, %s, %s, %s, %s, %s)""",
        (tick, at, kind, monitor_id, patient_id, message, Jsonb(data or {}), actor_id),
    )


def log_event(conn: psycopg.Connection, kind: str, message: str, **kwargs: Any) -> None:
    state = conn.execute("select tick, sim_time from public.sim_state where id = 1").fetchone()
    tick = state["tick"] if state else 0
    _event(conn, tick, datetime.now(UTC), kind, message, **kwargs)


def load_thresholds(conn: psycopg.Connection) -> tuple[dict[str, dict], dict[Any, dict[str, dict]]]:
    defaults: dict[str, dict] = {p: {"low": lo, "high": hi, "enabled": True} for p, (lo, hi) in DEFAULT_THRESHOLDS.items()}
    overrides: dict[Any, dict[str, dict]] = {}
    for row in conn.execute("select patient_id, parameter, low, high, enabled from public.thresholds"):
        entry = {"low": _num(row["low"]), "high": _num(row["high"]), "enabled": row["enabled"]}
        if row["patient_id"] is None:
            defaults[row["parameter"]] = entry
        else:
            overrides.setdefault(row["patient_id"], {})[row["parameter"]] = entry
    return defaults, overrides


def _num(value: Any) -> float | None:
    return None if value is None else float(value)


def effective_thresholds(defaults: dict, overrides: dict, patient_id: Any) -> dict[str, dict]:
    merged = {p: dict(v) for p, v in defaults.items()}
    for p, v in overrides.get(patient_id, {}).items():
        merged[p] = {**v, "source": "patient"}
    for v in merged.values():
        v.setdefault("source", "default")
    return merged


# --------------------------------------------------------------------------- vitals generation
def _approach(prev: float | None, target: float, alpha: float, noise: float, rng: random.Random) -> float:
    base = target if prev is None else prev + (target - prev) * alpha
    return base + rng.gauss(0, noise)


def _generate(monitor: dict, baseline: dict, tick: int, seed: int) -> tuple[dict, dict]:
    """Return (reading, new_state) for one monitor at one tick."""
    rng = random.Random(f"{seed}:{tick}:{monitor['id']}")
    state = dict(monitor["sim_state"] or {})
    scenario = monitor["scenario"]
    phase = state.get("phase", rng.random() * 6.28)
    drift = math.sin(tick / 18.0 + phase)

    hr_t = baseline.get("hr", 78) + 4 * drift
    spo2_t = baseline.get("spo2", 97) + 0.6 * drift
    rr_t = baseline.get("rr", 16) + 1.2 * drift
    sys_t = baseline.get("sys", 122) + 5 * drift
    dia_t = baseline.get("dia", 76) + 3 * drift
    if scenario == "low_spo2":
        depth = min(1.0, state.get("episode", 0) / 6.0)
        spo2_t = spo2_t - (spo2_t - 83) * depth
        hr_t += 22 * depth
        rr_t += 9 * depth
        state["episode"] = state.get("episode", 0) + 1
    else:
        state["episode"] = 0

    hr = _approach(state.get("hr"), hr_t, 0.45, 1.6, rng)
    spo2 = min(100.0, _approach(state.get("spo2"), spo2_t, 0.5, 0.5, rng))
    rr = max(4.0, _approach(state.get("rr"), rr_t, 0.4, 0.8, rng))
    sys = _approach(state.get("sys"), sys_t, 0.4, 2.5, rng)
    dia = _approach(state.get("dia"), dia_t, 0.4, 1.8, rng)
    state.update({"hr": hr, "spo2": spo2, "rr": rr, "sys": sys, "dia": dia, "phase": phase})

    battery = float(monitor["battery_pct"])
    if scenario == "weak_battery":
        battery = max(3.0, battery - rng.uniform(1.5, 2.6))
    else:
        battery = min(100.0, battery + 0.8)

    sensor = "ok"
    if scenario == "sensor_issue":
        sensor = "spo2_probe_off" if (tick // 8) % 2 == 0 else "ecg_leads_off"

    reading = {
        "heart_rate": None if sensor == "ecg_leads_off" else round(hr),
        "spo2": None if sensor == "spo2_probe_off" else round(spo2),
        "resp_rate": round(rr),
        "systolic": round(sys),
        "diastolic": round(dia),
        "battery_pct": round(battery, 2),
        "quality": "artifact" if sensor != "ok" else "good",
    }
    return reading, state | {"sensor": sensor, "battery": battery}


# --------------------------------------------------------------------------- alarm evaluation
def evaluate_conditions(reading: dict | None, monitor: dict, thresholds: dict, offline_seconds: float,
                        tick_seconds: int) -> tuple[dict[str, dict], set[str]]:
    """Return (conditions present, alarm types that could be evaluated)."""
    present: dict[str, dict] = {}
    evaluable: set[str] = {"battery_low", "sensor_issue", "connection_lost"}

    battery = float(monitor["battery_pct"])
    if battery < 20:
        present["battery_low"] = {"severity": "critical" if battery < 10 else "warning", "value": round(battery, 1),
                                  "threshold": 20, "message": f"Battery at {battery:.0f}% - replace or connect to mains"}
    if monitor["connection"] == "offline" and offline_seconds >= 2 * tick_seconds:
        present["connection_lost"] = {"severity": "critical", "value": round(offline_seconds), "threshold": 2 * tick_seconds,
                                      "message": f"No data received for {offline_seconds:.0f} s - patient is not monitored"}
    if monitor["sensor_status"] != "ok":
        text = "SpO2 probe off" if monitor["sensor_status"] == "spo2_probe_off" else "ECG leads off"
        present["sensor_issue"] = {"severity": "warning", "value": None, "threshold": None,
                                   "message": f"{text} - check sensor placement"}

    if reading is None:
        return present, evaluable

    def check(field: str, value: float | None, high_type: str | None, low_type: str | None,
              crit_high: float, crit_low: float, unit: str, label: str) -> None:
        if value is None:
            return
        t = thresholds.get(field, {})
        if high_type:
            evaluable.add(high_type)
        if low_type:
            evaluable.add(low_type)
        if not t.get("enabled", True):
            return
        high, low = t.get("high"), t.get("low")
        if high_type and high is not None and value > high:
            present[high_type] = {"severity": "critical" if value >= crit_high else "warning", "value": value,
                                  "threshold": high, "message": f"{label} {value:.0f} {unit} above limit {high:.0f}"}
        if low_type and low is not None and value < low:
            present[low_type] = {"severity": "critical" if value <= crit_low else "warning", "value": value,
                                 "threshold": low, "message": f"{label} {value:.0f} {unit} below limit {low:.0f}"}

    check("heart_rate", reading["heart_rate"], "hr_high", "hr_low", 150, 40, "bpm", "Heart rate")
    check("spo2", reading["spo2"], None, "spo2_low", 999, 85, "%", "SpO2")
    check("resp_rate", reading["resp_rate"], "rr_high", "rr_low", 35, 6, "/min", "Respiratory rate")
    check("systolic", reading["systolic"], "bp_high", "bp_low", 190, 75, "mmHg", "Systolic BP")
    if reading["diastolic"] is not None and "bp_high" not in present:
        t = thresholds.get("diastolic", {})
        if t.get("enabled", True) and t.get("high") is not None and reading["diastolic"] > t["high"]:
            present["bp_high"] = {"severity": "warning", "value": reading["diastolic"], "threshold": t["high"],
                                  "message": f"Diastolic BP {reading['diastolic']:.0f} mmHg above limit {t['high']:.0f}"}
    return present, evaluable


def _page(conn: psycopg.Connection, tick: int, at: datetime, monitor_id: str, bed_id: str, alarm_type: str) -> None:
    """Simulated external integration: page the charge nurse for critical alarms."""
    conn.execute(
        """insert into public.integration_outbox (channel, recipient, subject, payload)
           values ('pager', %s, %s, %s)""",
        ("ward-4b-charge-nurse", f"CRITICAL {ALARM_LABELS[alarm_type]} - {bed_id}",
         Jsonb({"bed": bed_id, "monitor": monitor_id, "type": alarm_type, "tick": tick})),
    )
    _event(conn, tick, at, "integration", f"Pager notified (simulated): {ALARM_LABELS[alarm_type]} on {bed_id}",
           monitor_id=monitor_id, data={"channel": "pager"})


def sync_alarms(conn: psycopg.Connection, monitor: dict, patient_id: Any, bed_id: str, tick: int, at: datetime,
                present: dict[str, dict], evaluable: set[str]) -> None:
    active = {
        row["type"]: row
        for row in conn.execute(
            "select id, type, severity from public.alarms where monitor_id = %s and state = 'active'", (monitor["id"],)
        )
    }
    for alarm_type, cond in present.items():
        category = "technical" if alarm_type in ("battery_low", "sensor_issue", "connection_lost") else "physiological"
        if alarm_type in active:
            conn.execute(
                """update public.alarms set last_seen_at = %s, value = %s, severity = %s, message = %s
                   where id = %s""",
                (at, cond["value"], cond["severity"], cond["message"], active[alarm_type]["id"]),
            )
            if cond["severity"] == "critical" and active[alarm_type]["severity"] != "critical":
                _event(conn, tick, at, "alarm_escalated", f"{ALARM_LABELS[alarm_type]} on {bed_id} escalated to critical",
                       monitor_id=monitor["id"], patient_id=patient_id, data={"type": alarm_type})
                _page(conn, tick, at, monitor["id"], bed_id, alarm_type)
            continue
        conn.execute(
            """insert into public.alarms (monitor_id, patient_id, bed_id, type, category, severity, message, value,
                   threshold, state, raised_at, raised_tick, last_seen_at)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s, %s)""",
            (monitor["id"], patient_id, bed_id, alarm_type, category, cond["severity"], cond["message"], cond["value"],
             cond["threshold"], at, tick, at),
        )
        _event(conn, tick, at, "alarm_raised", f"{ALARM_LABELS[alarm_type]} on {bed_id}: {cond['message']}",
               monitor_id=monitor["id"], patient_id=patient_id, data={"type": alarm_type, "severity": cond["severity"]})
        if cond["severity"] == "critical":
            _page(conn, tick, at, monitor["id"], bed_id, alarm_type)

    for alarm_type, row in active.items():
        if alarm_type not in present and alarm_type in evaluable:
            conn.execute("update public.alarms set state = 'resolved', resolved_at = %s where id = %s", (at, row["id"]))
            _event(conn, tick, at, "alarm_resolved", f"{ALARM_LABELS[alarm_type]} on {bed_id} resolved",
                   monitor_id=monitor["id"], patient_id=patient_id, data={"type": alarm_type})


def resolve_monitor_alarms(conn: psycopg.Connection, monitor_id: str, reason: str) -> int:
    rows = conn.execute(
        """update public.alarms set state = 'resolved', resolved_at = now(),
               message = message || %s
           where monitor_id = %s and state = 'active' returning id""",
        (f" ({reason})", monitor_id),
    ).fetchall()
    return len(rows)


# --------------------------------------------------------------------------- tick loop
def advance(conn: psycopg.Connection, steps: int, retention_days: int = 7) -> dict[str, Any]:
    state = conn.execute("select * from public.sim_state where id = 1 for update").fetchone()
    if state is None:
        raise RuntimeError("Simulation state missing - run the seed")
    tick_seconds = state["tick_seconds"]
    now = datetime.now(UTC)
    sim_time = state["sim_time"]
    # Keep the simulated clock anchored to wall time: backfill a gap instead of leaving it.
    earliest = now - timedelta(seconds=tick_seconds * steps)
    if sim_time < earliest:
        sim_time = earliest
    defaults, overrides = load_thresholds(conn)
    raised_before = conn.execute("select count(*) as n from public.alarms").fetchone()["n"]

    for _ in range(steps):
        tick = state["tick"] + 1
        sim_time = sim_time + timedelta(seconds=tick_seconds)
        monitors = conn.execute(
            """select m.*, p.id as patient_id, p.baseline
               from public.monitors m
               left join public.patients p on p.bed_id = m.bed_id and p.status = 'admitted'
               where m.status = 'active'
               order by m.id"""
        ).fetchall()
        for m in monitors:
            reading, new_state = _generate(m, m["baseline"] or {}, tick, state["seed"])
            online = m["scenario"] != "lost_connection"
            last_seen = sim_time if online else (m["last_seen_at"] or sim_time)
            m.update({"battery_pct": new_state["battery"], "connection": "online" if online else "offline",
                      "sensor_status": new_state["sensor"], "last_seen_at": last_seen})
            conn.execute(
                """update public.monitors set battery_pct = %s, connection = %s, sensor_status = %s, sim_state = %s,
                       last_seen_at = %s, updated_at = now() where id = %s""",
                (round(new_state["battery"], 2), m["connection"], m["sensor_status"],
                 Jsonb({k: v for k, v in new_state.items() if k not in ("sensor", "battery")}), last_seen, m["id"]),
            )
            if m["bed_id"] is None or m["patient_id"] is None:
                continue
            if online:
                conn.execute(
                    """insert into public.vital_readings (monitor_id, patient_id, bed_id, tick, recorded_at, heart_rate,
                           spo2, resp_rate, systolic, diastolic, battery_pct, quality)
                       values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (m["id"], m["patient_id"], m["bed_id"], tick, sim_time, reading["heart_rate"], reading["spo2"],
                     reading["resp_rate"], reading["systolic"], reading["diastolic"], reading["battery_pct"],
                     reading["quality"]),
                )
            offline_seconds = (sim_time - last_seen).total_seconds()
            thresholds = effective_thresholds(defaults, overrides, m["patient_id"])
            present, evaluable = evaluate_conditions(reading if online else None, m, thresholds, offline_seconds,
                                                     tick_seconds)
            sync_alarms(conn, m, m["patient_id"], m["bed_id"], tick, sim_time, present, evaluable)
        state["tick"] = tick

    conn.execute(
        "update public.sim_state set tick = %s, sim_time = %s, last_advanced_at = now(), updated_at = now() where id = 1",
        (state["tick"], sim_time),
    )
    if state["tick"] % 50 < steps or steps >= 50:
        conn.execute("select public.purge_expired_data(make_interval(days => %s))", (retention_days,))
    raised_after = conn.execute("select count(*) as n from public.alarms").fetchone()["n"]
    return {"tick": state["tick"], "sim_time": sim_time, "steps": steps, "alarms_raised": raised_after - raised_before}


def set_scenario(conn: psycopg.Connection, monitor_id: str, scenario: str, actor_id: Any = None) -> dict | None:
    row = conn.execute(
        "update public.monitors set scenario = %s, updated_at = now() where id = %s returning id, bed_id",
        (scenario, monitor_id),
    ).fetchone()
    if row:
        if scenario != "sensor_issue":
            conn.execute("update public.monitors set sensor_status = 'ok' where id = %s", (monitor_id,))
        log_event(conn, "scenario_change", f"{monitor_id} scenario set to '{SCENARIO_LABELS[scenario]}'",
                  monitor_id=monitor_id, data={"scenario": scenario}, actor_id=actor_id)
    return row
