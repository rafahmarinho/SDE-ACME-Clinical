"""Demo data: 12 fictional patients, 12 beds and 10 simulated monitors.

All people, record numbers and clinical details are fictional. `reset_demo_data` restores the
ward to its initial state (staff accounts, audit trail and sessions are preserved).
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.security.crypto import encrypt_text
from app.services import simulation

DEMO_STAFF = [
    {"key": "nurse", "full_name": "Nora Bennett", "role": "nurse", "job_title": "Registered Nurse"},
    {"key": "physician", "full_name": "Amelia Hart", "role": "physician", "job_title": "Attending Physician"},
    {"key": "biomed", "full_name": "Theo Okafor", "role": "biomed", "job_title": "Biomedical Technician"},
    {"key": "admin", "full_name": "Avery Morgan", "role": "admin", "job_title": "Clinical Systems Administrator"},
]

BEDS = [
    {"id": f"B{i:02d}", "label": f"Bed {i}", "room": f"4B-{(i + 1) // 2:02d}",
     "pos_x": (i - 1) % 6 * 3.2 - 8.0, "pos_z": -3.5 if i <= 6 else 3.5}
    for i in range(1, 13)
]

PATIENTS: list[dict[str, Any]] = [
    {"mrn": "ACM-104201", "first": "Margaret", "last": "Ellison", "dob": date(1948, 3, 14), "sex": "female",
     "dx": "Community-acquired pneumonia", "doc": "Amelia Hart", "acuity": "high", "allergies": "Penicillin",
     "code": "Full code", "base": {"hr": 92, "spo2": 94, "rr": 20, "sys": 128, "dia": 74}},
    {"mrn": "ACM-104202", "first": "Daniel", "last": "Okoro", "dob": date(1961, 7, 2), "sex": "male",
     "dx": "Heart failure exacerbation", "doc": "Rajesh Menon", "acuity": "high", "allergies": "None known",
     "code": "Full code", "base": {"hr": 88, "spo2": 95, "rr": 19, "sys": 138, "dia": 82}},
    {"mrn": "ACM-104203", "first": "Lucia", "last": "Fernandes", "dob": date(1955, 11, 23), "sex": "female",
     "dx": "COPD exacerbation", "doc": "Amelia Hart", "acuity": "high", "allergies": "Sulfa drugs",
     "code": "DNR", "base": {"hr": 86, "spo2": 93, "rr": 21, "sys": 132, "dia": 78}},
    {"mrn": "ACM-104204", "first": "Henry", "last": "Whitaker", "dob": date(1972, 1, 9), "sex": "male",
     "dx": "Post-operative hip replacement", "doc": "Carla Ortiz", "acuity": "medium", "allergies": "None known",
     "code": "Full code", "base": {"hr": 74, "spo2": 97, "rr": 15, "sys": 124, "dia": 76}},
    {"mrn": "ACM-104205", "first": "Priya", "last": "Raman", "dob": date(1989, 5, 30), "sex": "female",
     "dx": "Diabetic ketoacidosis - resolving", "doc": "Rajesh Menon", "acuity": "medium", "allergies": "Latex",
     "code": "Full code", "base": {"hr": 96, "spo2": 98, "rr": 18, "sys": 116, "dia": 70}},
    {"mrn": "ACM-104206", "first": "Samuel", "last": "Brooks", "dob": date(1966, 9, 17), "sex": "male",
     "dx": "Atrial fibrillation with rapid ventricular response", "doc": "Amelia Hart", "acuity": "high",
     "allergies": "None known", "code": "Full code", "base": {"hr": 104, "spo2": 96, "rr": 17, "sys": 130, "dia": 84}},
    {"mrn": "ACM-104207", "first": "Grace", "last": "Lindqvist", "dob": date(1993, 2, 6), "sex": "female",
     "dx": "Post-operative appendectomy", "doc": "Carla Ortiz", "acuity": "low", "allergies": "None known",
     "code": "Full code", "base": {"hr": 72, "spo2": 99, "rr": 14, "sys": 118, "dia": 72}},
    {"mrn": "ACM-104208", "first": "Omar", "last": "Haddad", "dob": date(1958, 12, 1), "sex": "male",
     "dx": "Sepsis - urinary source, improving", "doc": "Rajesh Menon", "acuity": "high", "allergies": "Vancomycin",
     "code": "Full code", "base": {"hr": 98, "spo2": 95, "rr": 20, "sys": 108, "dia": 64}},
    {"mrn": "ACM-104209", "first": "Ruth", "last": "Castellano", "dob": date(1940, 4, 19), "sex": "female",
     "dx": "Ischaemic stroke - observation", "doc": "Amelia Hart", "acuity": "medium", "allergies": "Aspirin",
     "code": "DNR/DNI", "base": {"hr": 70, "spo2": 96, "rr": 16, "sys": 148, "dia": 86}},
    {"mrn": "ACM-104210", "first": "Ethan", "last": "Mwangi", "dob": date(2001, 8, 11), "sex": "male",
     "dx": "Severe asthma exacerbation", "doc": "Carla Ortiz", "acuity": "medium", "allergies": "None known",
     "code": "Full code", "base": {"hr": 90, "spo2": 96, "rr": 19, "sys": 120, "dia": 74}},
    {"mrn": "ACM-104211", "first": "Helen", "last": "Kowalski", "dob": date(1952, 6, 27), "sex": "female",
     "dx": "Upper GI bleed - stable", "doc": "Rajesh Menon", "acuity": "medium", "allergies": "None known",
     "code": "Full code", "base": {"hr": 84, "spo2": 98, "rr": 16, "sys": 112, "dia": 68}},
    {"mrn": "ACM-104212", "first": "Victor", "last": "Almeida", "dob": date(1979, 10, 4), "sex": "male",
     "dx": "Acute pancreatitis", "doc": "Carla Ortiz", "acuity": "low", "allergies": "Codeine",
     "code": "Full code", "base": {"hr": 82, "spo2": 98, "rr": 17, "sys": 126, "dia": 80}},
]

MONITOR_MODELS = ["Vitalis M5", "Vitalis M5", "Vitalis M7", "Vitalis M5", "Vitalis M7",
                  "Vitalis M5", "Vitalis M7", "Vitalis M5", "Vitalis M7", "Vitalis M5"]

_DOMAIN_TABLES = (
    "public.vital_readings", "public.alarms", "public.notes", "public.maintenance_records",
    "public.monitor_assignments", "public.sim_events", "public.integration_outbox", "public.thresholds",
    "public.emergency_access", "public.reports", "public.device_nonces",
)


def _staff_ids(conn: psycopg.Connection) -> dict[str, Any]:
    rows = conn.execute("select id, role, full_name from public.profiles where active order by created_at").fetchall()
    by_role: dict[str, Any] = {}
    for row in rows:
        by_role.setdefault(row["role"], row)
    return by_role


def reset_demo_data(conn: psycopg.Connection, seed: int = 4242, history_ticks: int = 120) -> list[str]:
    """Wipe and recreate all ward data. Returns storage paths of reports that should be deleted."""
    report_paths = [r["storage_path"] for r in conn.execute(
        "select storage_path from public.reports where storage_path is not null")]
    for table in _DOMAIN_TABLES:
        conn.execute(f"delete from {table}")  # noqa: S608 - fixed table names, no user input
    conn.execute("update public.patients set bed_id = null")
    conn.execute("delete from public.patients")
    conn.execute("delete from public.monitors")
    conn.execute("delete from public.beds")

    for bed in BEDS:
        conn.execute("insert into public.beds (id, label, room, pos_x, pos_z) values (%s, %s, %s, %s, %s)",
                     (bed["id"], bed["label"], bed["room"], bed["pos_x"], bed["pos_z"]))

    now = datetime.now(UTC)
    start = now - timedelta(seconds=5 * history_ticks)
    patient_ids: dict[str, Any] = {}
    for i, p in enumerate(PATIENTS, start=1):
        row = conn.execute(
            """insert into public.patients (mrn, first_name, last_name, date_of_birth, sex, bed_id, admitted_at,
                   diagnosis, attending_physician, acuity, allergies, code_status, baseline)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
            (p["mrn"], p["first"], p["last"], p["dob"], p["sex"], f"B{i:02d}", now - timedelta(hours=6 + i * 7),
             p["dx"], p["doc"], p["acuity"], p["allergies"], p["code"], Jsonb(p["base"])),
        ).fetchone()
        patient_ids[f"B{i:02d}"] = row["id"]

    staff = _staff_ids(conn)
    tech = staff.get("biomed")
    for i in range(1, 11):
        monitor_id = f"MON-{i:02d}"
        bed_id = f"B{i:02d}" if i <= 9 else None
        battery = {2: 64.0, 9: 41.0}.get(i, 100.0)
        conn.execute(
            """insert into public.monitors (id, serial_number, model, firmware, bed_id, status, battery_pct,
                   last_seen_at, last_maintenance_at, next_maintenance_due)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (monitor_id, f"VTL-{2026}{i:04d}", MONITOR_MODELS[i - 1], "4.2.1" if i % 3 else "4.1.7", bed_id,
             "active" if bed_id else "standby", battery, start, now - timedelta(days=30 + i * 9),
             (now + timedelta(days=60 - i * 7)).date()),
        )
        if bed_id:
            conn.execute(
                """insert into public.monitor_assignments (monitor_id, bed_id, patient_id, assigned_by, assigned_at)
                   values (%s, %s, %s, %s, %s)""",
                (monitor_id, bed_id, patient_ids[bed_id], tech["id"] if tech else None, now - timedelta(hours=5 + i)),
            )

    for parameter, (low, high) in simulation.DEFAULT_THRESHOLDS.items():
        conn.execute("insert into public.thresholds (patient_id, parameter, low, high) values (null, %s, %s, %s)",
                     (parameter, low, high))
    # COPD patient: accepted lower saturation target (physician order).
    conn.execute("insert into public.thresholds (patient_id, parameter, low, high) values (%s, 'spo2', 88, null)",
                 (patient_ids["B03"],))
    # AF patient: tolerated higher heart rate while rate control is titrated.
    conn.execute("insert into public.thresholds (patient_id, parameter, low, high) values (%s, 'heart_rate', 50, 130)",
                 (patient_ids["B06"],))

    tech_name = tech["full_name"] if tech else "Biomedical Engineering"
    records = [
        ("MON-04", "calibration", "completed", "Annual NIBP calibration", "Within tolerance (+/-2 mmHg)", 40),
        ("MON-07", "sensor_replacement", "completed", "SpO2 probe cable frayed", "Replaced probe and cable", 18),
        ("MON-02", "battery_replacement", "open", "Battery holds charge for less than 2 hours", None, 1),
        ("MON-10", "inspection", "in_progress", "Pre-deployment electrical safety inspection", None, 0),
    ]
    for monitor_id, kind, status, desc, resolution, days_ago in records:
        opened = now - timedelta(days=days_ago, hours=3)
        conn.execute(
            """insert into public.maintenance_records (monitor_id, type, status, description, resolution, opened_by,
                   opened_by_name, completed_by, completed_by_name, opened_at, completed_at)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (monitor_id, kind, status, desc, resolution, tech["id"] if tech else None, tech_name,
             (tech["id"] if tech else None) if status == "completed" else None,
             tech_name if status == "completed" else None, opened,
             opened + timedelta(hours=4) if status == "completed" else None),
        )

    nurse = staff.get("nurse")
    physician = staff.get("physician")
    notes = [
        ("B01", nurse, "nursing", "Productive cough overnight. Encouraged incentive spirometry every hour while awake."),
        ("B01", physician, "physician", "Continue IV ceftriaxone. Repeat chest X-ray tomorrow morning."),
        ("B03", physician, "physician", "Target SpO2 88-92% (chronic CO2 retainer). Avoid high-flow oxygen."),
        ("B06", nurse, "handover", "Rate control with metoprolol started at 14:00. Monitor for hypotension."),
        ("B08", nurse, "nursing", "Afebrile since midnight. Urine output adequate."),
    ]
    for offset, (bed, author, category, text) in enumerate(notes):
        pid = patient_ids[bed]
        row = conn.execute(
            """insert into public.notes (patient_id, author_id, category, body_encrypted, created_at)
               values (%s, %s, %s, 'pending', %s) returning id""",
            (pid, author["id"] if author else None, category, now - timedelta(minutes=200 - offset * 30)),
        ).fetchone()
        conn.execute("update public.notes set body_encrypted = %s where id = %s",
                     (encrypt_text(text, f"note:{row['id']}"), row["id"]))

    conn.execute(
        """insert into public.sim_state (id, tick, sim_time, seed, tick_seconds, auto_run, last_advanced_at)
           values (1, 0, %s, %s, 5, false, null)
           on conflict (id) do update set tick = 0, sim_time = excluded.sim_time, seed = excluded.seed,
               tick_seconds = 5, auto_run = false, last_advanced_at = null, updated_at = now()""",
        (start, seed),
    )
    simulation.log_event(conn, "reset", "Demo data reset: 12 patients, 12 beds, 10 monitors")
    if history_ticks:
        simulation.advance(conn, max(1, history_ticks - 12))
        simulation.set_scenario(conn, "MON-03", "low_spo2")
        simulation.set_scenario(conn, "MON-09", "weak_battery")
        simulation.advance(conn, 12)
    return report_paths
