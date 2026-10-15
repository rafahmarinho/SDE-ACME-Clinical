# ACME Clinical

Ward patient-monitoring system for **Ward 4B**: ward overview, patient list and charts, live monitoring with a synthetic ECG, alarms that stay visible until the condition clears, monitor-to-bed assignment, maintenance tracking, alarm limits, reports, team management, a 3D ward view and a simulation console.

> **Demonstration only.** All patients, record numbers and clinical details are fictional and the bedside monitors are simulated. ACME Clinical is not a medical device and must not be used for patient care.

| Layer | Technology |
| --- | --- |
| Web app | React 19, Vite 8, TypeScript 7, React Router 8, TanStack Query 5, three.js / React Three Fiber (3D ward), pnpm |
| API | Python 3.12+, FastAPI, Pydantic 2, psycopg 3 — readings, alarms, ECG and reports are generated in Python |
| Platform | Supabase: PostgreSQL (RLS), Auth (e-mail + password, TOTP MFA, password recovery), Storage (private buckets), Realtime |
| Hosting | Two Vercel projects: `frontend/` (static SPA) and `backend/` (Python serverless function) |

## Contents

```
backend/                FastAPI service
  app/config.py         validated settings
  app/db.py             database access (pooled psycopg, bound parameters only)
  app/routers/          HTTP endpoints (auth, me, ward, patients, alarms, devices, reports, simulation, team, admin, ingest)
  app/services/         simulation engine, ECG generator, reports, seed data, audit trail, Supabase gateway
  app/security/         JWT/session enforcement, central RBAC, crypto, rate limiting, password policy
  app/schemas/          Pydantic request models (strict validation)
  scripts/seed.py       creates the 4 demo staff accounts and loads the demo ward
  scripts/device_emulator.py  pushes HMAC-signed readings like an external monitor
  tests/                87 security + functional tests (real PostgreSQL via PGlite, mock Supabase)
  tools/local_stack.py  offline demo stack (no Supabase needed)
frontend/
  src/screens/          pages (login, ward, patients, monitoring, alarms, devices, reports, simulation, team, audit, profile, settings)
  src/components/       UI building blocks (bed cards, ECG canvas, trend charts, 3D ward, dialogs)
  src/services/         API client, Supabase client, auth, realtime, endpoint functions, types
  src/hooks/            auth/session (idle timeout), realtime with polling fallback, toasts
supabase/migrations/    database schema, RLS policies, least-privilege API role, realtime publication, storage buckets
docs/                   threat model, security controls (SD Elements mapping), privacy documentation
```

## Roles

| Role | Sees / can do |
| --- | --- |
| **Nurse** | Ward overview, patients, live monitoring, alarms (acknowledge clinical + technical), notes, assign monitors to beds, report device problems, reports |
| **Physician** | Everything a nurse sees, plus physician notes, patient-specific alarm limits, ward default limits, edit clinical details |
| **Biomedical technician** | Device-centric ward view (no patient identities or vitals), devices, maintenance, technical alarms, simulation console, device reports, time-limited **break-glass** access to a single chart with a justification |
| **Administrator** | Team management (invite, roles, deactivate, erase personal data), audit log with integrity check, privacy requests, security configuration, simulation console and **demo reset**; restrict patient data from secondary use. Admin actions require two-factor authentication (AAL2). |

Navigation, buttons and pages adapt to the permissions returned by `GET /me`; the API enforces every permission again on each request.

## Demo data

`scripts/seed.py` (or the reset button in the simulation console) creates **12 fictional patients in 12 beds and 10 simulated monitors** (9 on beds, `MON-10` on standby), ward default alarm limits plus two physician-ordered patient limits, maintenance history and encrypted clinical notes. About 10 minutes of history are generated, then Bed 3 starts desaturating and Bed 9's monitor runs on a weak battery so alarms are visible immediately.

Scenarios per monitor: **normal readings, low oxygen saturation, weak battery, sensor issue** (SpO₂ probe off / ECG leads off) and **lost connection** (watchdog raises *Connection lost* after two missed ticks). Presets: all normal, desaturation, battery round, sensor trouble, network outage, busy shift. Each tick is 5 simulated seconds; advance manually (+1 tick, +1 min, +5 min) or press **Run simulation** in *Live monitoring*.

**Acknowledging an alarm never clears it**: it records who responded and when; the alarm stays *Active · acknowledged* until the simulator observes that the condition is gone. Critical alarms page the charge nurse through a simulated pager (see *Integration outbox*). Reports filed to the EHR and privacy-office notifications are simulated the same way.

---

## 1. Run locally with Supabase

Prerequisites: Python 3.12+, Node.js 22+, pnpm 10, a Supabase project.

### 1.1 Database

1. In the Supabase dashboard open **SQL Editor** and run `supabase/migrations/20261012000000_acme_clinical.sql` (or `supabase db push` with the CLI).
2. Give the least-privilege API role a strong password (store it in your password manager, never in the repo):
   ```sql
   alter role acme_api with password '<generate a long random password>';
   ```
3. **Settings → Database → Connection pooling**: copy the *transaction* pooler URI (port 6543) and replace the user with `acme_api.<project-ref>`. Append `?sslmode=require`.

### 1.2 Auth settings (dashboard → Authentication)

- **Sign In / Providers → Email**: enabled; **disable "Allow new users to sign up"** (accounts are created by invitation only).
- **Password requirements**: minimum length 12, require lowercase, uppercase, digits and symbols; enable leaked-password protection if your plan allows.
- **Multi-Factor**: enable TOTP.
- **URL Configuration**: Site URL = your web app URL; add `https://<web-app>/reset-password` and `https://<web-app>/accept-invite` (and the `http://localhost:5173/...` equivalents for local work) to **Redirect URLs**.
- **Rate limits**: keep the defaults or lower them. **SMTP**: configure a custom SMTP sender for production (SPF/DKIM aligned).

### 1.3 API

```bash
cd backend
python -m venv .venv
```
```bash
.venv/bin/pip install -r requirements-dev.txt        # Windows: .venv\Scripts\pip
```
```bash
cp .env.example .env                                  # then fill in every value
```
```bash
.venv/bin/python -m scripts.seed                      # needs DEMO_PASSWORD in .env
```
```bash
.venv/bin/uvicorn app.main:app --reload --port 8000
```

The seed prints the four demo accounts (`nora.bennett@…` nurse, `amelia.hart@…` physician, `theo.okafor@…` biomedical technician, `avery.morgan@…` administrator). The password is the `DEMO_PASSWORD` you chose. Use real mailboxes (set `DEMO_EMAIL_DOMAIN`) if you want to test password-recovery e-mails. The administrator must set up two-factor authentication in **Settings → Security** before using Team, Audit log or Reset (set `REQUIRE_ADMIN_MFA=false` only for local experiments).

### 1.4 Web app

```bash
cd frontend
pnpm install
```
```bash
cp .env.example .env.local                            # VITE_API_URL, VITE_SUPABASE_URL, VITE_SUPABASE_PUBLISHABLE_KEY
```
```bash
pnpm dev
```

Open http://localhost:5173.

## 2. Offline demo (no Supabase account)

For a quick look on one machine, `backend/tools/local_stack.py` starts an in-memory PostgreSQL 17 (PGlite) with the real migration, a mock of Supabase Auth/Storage and the API, and seeds the demo:

```bash
cd backend/tests/pglite && npm install
```
```bash
cd backend && .venv/bin/python tools/local_stack.py
```

Then create `frontend/.env.development.local` with `VITE_API_URL=http://127.0.0.1:8000`, `VITE_SUPABASE_URL=http://127.0.0.1:54321`, `VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_local_offline_demo` and run `pnpm dev`. Sign in with any demo account and the password `Ward4B-Demo!2026` (offline stack only; override with `DEMO_PASSWORD`). Realtime is not emulated, so the header shows *Live updates degraded · polling* and screens refresh every 5 s. Data disappears when the process stops.

## 3. Tests

```bash
cd backend && .venv/bin/python -m pytest          # 87 tests: auth, sessions, RBAC, RLS, injection, headers, alarms, reports, privacy, audit
```
```bash
cd frontend && pnpm typecheck && pnpm test && pnpm build
```
```bash
cd backend && .venv/bin/pip-audit -r requirements.txt
```
```bash
cd frontend && pnpm audit --prod
```

The backend suite runs against a real PostgreSQL 17 (PGlite, `backend/tests/pglite`) with the production migration applied and a mock Supabase (`backend/tests/mock_supabase.py`). `.github/workflows/ci.yml` runs everything on each push.

## 4. Deploy on Vercel

Create **two** Vercel projects from the same repository.

### 4.1 API (`backend/`)

1. *New Project* → import the repository → **Root Directory: `backend`**. Vercel detects FastAPI (`index.py` exports `app`) and installs `requirements.txt`; `.python-version` pins Python 3.12.
2. Environment variables (Production and Preview, marked *Sensitive*): everything in `backend/.env.example` with `ENVIRONMENT=production`, `APP_URL=https://<web>.vercel.app`, `ALLOWED_ORIGINS=https://<web>.vercel.app`, the pooler `DATABASE_URL` with `sslmode=require`, the Supabase keys and four freshly generated 32-byte keys. Leave `DEMO_PASSWORD` unset.
3. Deploy, then check `https://<api>.vercel.app/health`. Interactive docs are disabled in production.
4. Seed once from your machine with the production `.env` (`python -m scripts.seed`) or reset from the simulation console.

### 4.2 Web app (`frontend/`)

1. *New Project* → same repository → **Root Directory: `frontend`**. `vercel.json` sets pnpm, the build and SPA rewrites and security headers.
2. Environment variables: `VITE_API_URL=https://<api>.vercel.app`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` (publishable key only). The build injects a Content-Security-Policy restricted to these origins.
3. Deploy, then add the production URLs to Supabase **Redirect URLs** and the API's `ALLOWED_ORIGINS`.

With the CLI: `vercel --cwd backend --prod` and `vercel --cwd frontend --prod` after `vercel link` in each folder.

### 4.3 Production checklist

- Separate Supabase projects and Vercel environments for development, preview and production.
- Rotate the four application keys and the `acme_api` password on a schedule; rotating `AUDIT_HMAC_KEY` starts a new chain (export and archive the old log first).
- Enable Supabase Point-in-Time Recovery/backups, network restrictions and log drains; review **Audit log → Verify integrity** regularly.
- Choose the Supabase region that meets your data-residency obligations.

## 5. Security and privacy

See [SECURITY.md](SECURITY.md), [docs/security/threat-model.md](docs/security/threat-model.md), [docs/security/controls.md](docs/security/controls.md) (SD Elements countermeasure mapping) and [docs/privacy/data-inventory.md](docs/privacy/data-inventory.md).

Highlights: sign-in proxied through the API (lockout, uniform errors, random delays, previous-login notice), server-enforced idle/absolute timeouts and logout that also cut off Realtime via RLS, concurrent-session limit, TOTP MFA for administrative actions, central role-based authorization with object-level checks and break-glass access, strict Pydantic validation, bound SQL parameters, AES-256-GCM encryption of clinical notes, HMAC-chained audit trail, de-identified reports with keyed pseudonyms, CSV formula-injection protection, re-encoded image uploads, HMAC-signed device ingestion with replay protection, CSP/HSTS/anti-framing headers, CORS allowlist and no cookies.
