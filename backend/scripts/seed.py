"""Create the four demo staff accounts in Supabase Auth and load the demo ward data.

Usage (from backend/, with .env configured):
    python -m scripts.seed

Requires DEMO_PASSWORD (it must satisfy the password policy; it is never printed or stored here).
Optional DEMO_EMAIL_DOMAIN (default: acme-clinical.example).
"""

import os
import sys

from app.config import get_settings
from app.db import transaction
from app.security import passwords
from app.services import audit, seed, supabase


def ensure_user(email: str, password: str, full_name: str) -> str:
    try:
        user = supabase.admin_create_user(email, password, {"full_name": full_name})
        return user["id"]
    except supabase.SupabaseError as exc:
        if exc.status not in (400, 409, 422):
            raise
        existing = supabase.admin_find_user_by_email(email)
        if existing is None:
            raise
        supabase.admin_update_user(existing["id"], {"password": password, "ban_duration": "none"})
        return existing["id"]


def main() -> int:
    get_settings()
    password = os.environ.get("DEMO_PASSWORD", "")
    domain = os.environ.get("DEMO_EMAIL_DOMAIN", "acme-clinical.example").strip().lower()
    issues = passwords.problems(password)
    if issues:
        print("DEMO_PASSWORD does not meet the password policy:", " ".join(issues), file=sys.stderr)
        return 2
    accounts = []
    for staff in seed.DEMO_STAFF:
        local = staff["full_name"].lower().replace(" ", ".")
        email = f"{local}@{domain}"
        user_id = ensure_user(email, password, staff["full_name"])
        accounts.append((user_id, email, staff))
    with transaction() as conn:
        for user_id, email, staff in accounts:
            conn.execute(
                """insert into public.profiles (id, email, full_name, role, job_title, active)
                   values (%s, %s, %s, %s, %s, true)
                   on conflict (id) do update set email = excluded.email, full_name = excluded.full_name,
                       role = excluded.role, job_title = excluded.job_title, active = true""",
                (user_id, email, staff["full_name"], staff["role"], staff["job_title"]),
            )
        stale = seed.reset_demo_data(conn)
        audit.record(conn, "seed.run", actor_email="seed-script", details={"accounts": len(accounts)})
    try:
        supabase.storage_remove("reports", stale)
    except supabase.SupabaseError:
        pass
    print("Demo data loaded. Staff accounts:")
    for _, email, staff in accounts:
        print(f"  {staff['role']:<10} {email}")
    print("Password: the value of DEMO_PASSWORD.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
