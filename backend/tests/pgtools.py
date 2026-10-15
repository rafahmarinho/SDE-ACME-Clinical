"""PGlite helpers shared by the test suite and the offline demo stack (no side effects on import)."""

import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT.parent / "supabase" / "migrations"


def apply_schema(conninfo: str) -> None:
    import psycopg

    with psycopg.connect(conninfo, autocommit=True) as conn:
        conn.execute((ROOT / "tests" / "sql" / "supabase_stub.sql").read_text(encoding="utf-8"))
        for path in sorted(MIGRATIONS.glob("*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))


def start_pglite(port: int) -> subprocess.Popen:
    """Start an in-memory PostgreSQL 17 (PGlite) listening on 127.0.0.1:<port>."""
    script = ROOT / "tests" / "pglite" / "server.mjs"
    if not (script.parent / "node_modules").exists():
        subprocess.run("npm install --no-audit --no-fund", cwd=script.parent, shell=True, check=True)
    proc = subprocess.Popen(["node", str(script), str(port)], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True)
    deadline = time.time() + 60
    while time.time() < deadline:
        line = proc.stdout.readline()
        if "PGLITE_READY" in line:
            # keep draining output so the server never blocks on a full pipe
            threading.Thread(target=lambda: [None for _ in proc.stdout], daemon=True).start()
            return proc
        if proc.poll() is not None:
            break
    proc.kill()
    raise RuntimeError("PGlite did not start")
