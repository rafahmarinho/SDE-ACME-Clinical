"""Offline demo stack - DEVELOPMENT ONLY.

Runs everything ACME Clinical needs on this machine without a Supabase project:
  * PostgreSQL 17 (PGlite, in memory)  -> 127.0.0.1:54329, with the real migration applied
  * Mock Supabase Auth + Storage        -> http://127.0.0.1:54321  (tests/mock_supabase.py)
  * ACME Clinical API                   -> http://127.0.0.1:8000

Realtime is not emulated, so the web app shows "Live updates degraded · polling" and refreshes by polling.
Data is lost when the process stops. Usage (from backend/):  python -m tools.local_stack
Demo password: value of DEMO_PASSWORD (default below is for this offline stack only).
"""

import base64
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PG_PORT = int(os.environ.get("LOCAL_PG_PORT", "54329"))
MOCK_PORT = int(os.environ.get("LOCAL_SUPABASE_PORT", "54321"))
API_PORT = int(os.environ.get("LOCAL_API_PORT", "8000"))
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "Ward4B-Demo!2026")


def _key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


os.environ.update({
    "ENVIRONMENT": "development",
    "DATABASE_URL": f"postgresql://postgres:postgres@127.0.0.1:{PG_PORT}/postgres?sslmode=disable",
    "DB_POOL_MAX_SIZE": "1",
    "SUPABASE_URL": f"http://127.0.0.1:{MOCK_PORT}",
    "SUPABASE_ANON_KEY": "sb_publishable_local_offline_demo",
    "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_local_offline_demo_key",
    "SUPABASE_JWT_SECRET": "local-offline-demo-jwt-secret-0123456789",
    "DATA_ENCRYPTION_KEY": _key(),
    "AUDIT_HMAC_KEY": _key(),
    "PSEUDONYM_KEY": _key(),
    "DEVICE_MASTER_KEY": _key(),
    "APP_URL": os.environ.get("APP_URL", "http://localhost:5173"),
    "ALLOWED_ORIGINS": os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:4173"),
    "REQUIRE_ADMIN_MFA": os.environ.get("REQUIRE_ADMIN_MFA", "false"),
})


def main() -> None:
    import uvicorn

    from tests.pgtools import apply_schema, start_pglite
    from tests import mock_supabase as mock

    pg = start_pglite(PG_PORT)
    apply_schema(os.environ["DATABASE_URL"])

    from app.db import transaction
    from app.services import seed

    with transaction() as conn:
        for s in seed.DEMO_STAFF:
            email = s["full_name"].lower().replace(" ", ".") + "@acme-clinical.example"
            user = mock.add_user(email, DEMO_PASSWORD)
            conn.execute("insert into public.profiles (id, email, full_name, role, job_title) values (%s, %s, %s, %s, %s)",
                         (user["id"], email, s["full_name"], s["role"], s["job_title"]))
            print(f"  {s['role']:<10} {email}")
        seed.reset_demo_data(conn)

    mock_server = uvicorn.Server(uvicorn.Config(mock.app, host="127.0.0.1", port=MOCK_PORT, log_level="warning"))
    threading.Thread(target=mock_server.run, daemon=True).start()
    time.sleep(1)
    print(f"Offline stack ready: API http://127.0.0.1:{API_PORT}  mock Supabase http://127.0.0.1:{MOCK_PORT}")
    try:
        uvicorn.run("app.main:app", host="127.0.0.1", port=API_PORT, log_level="info")
    finally:
        pg.terminate()


if __name__ == "__main__":
    main()
