# ACME Clinical — threat and risk assessment

Version 1.0 · 12 Oct 2026 · Source of requirements: SD Elements project 27 (survey: web application + REST API + frontend, PostgreSQL, health data, critical/emergency functions, personal data, email/password authentication, file upload, e-mail, cloud services). The survey also brought HIPAA and MDS2 into scope.

## 1. System and trust boundaries

```
 Clinician browser (SPA, React)  ──HTTPS + bearer JWT──►  ACME Clinical API (FastAPI, Vercel function)
        │  ▲                                                     │            │
        │  │ Realtime (WSS, RLS-filtered SELECT)                 │ TLS        │ HTTPS (secret key)
        ▼  │                                                     ▼            ▼
 Supabase Auth (GoTrue) ◄── token refresh, MFA ──   PostgreSQL (role acme_api, RLS)   Supabase Storage (private)
                                                                  ▲
 Simulated / external bedside monitors ──HTTPS + HMAC-signed readings──┘ (via /devices/ingest)
```

| Boundary | Crossing controls |
| --- | --- |
| Internet → SPA | Vercel TLS, HSTS, strict CSP, frame-ancestors none, no cookies |
| SPA → API | Bearer JWT verified (JWKS/HS256, aud, iss, exp), session registry (idle/absolute/revocation), RBAC, Pydantic validation, CORS allowlist, body limits |
| SPA → Supabase | Publishable key only; Realtime reads limited by RLS + live session; no direct writes (no INSERT/UPDATE grants) |
| API → PostgreSQL | Least-privilege login role over TLS, bound parameters, statement/lock timeouts |
| API → Supabase Auth/Storage | Secret key in server env only, HTTPS with certificate validation, fixed URLs |
| Devices → API | Per-device HMAC, 5-minute timestamp window, nonce replay protection |

## 2. Assets

| Asset | Classification | Why it matters |
| --- | --- | --- |
| Patient identity and clinical record (name, MRN, DOB, diagnosis, allergies, notes) | Restricted — health data (PHI) | Confidentiality, regulatory |
| Vital signs, ECG, alarms | Restricted — health data; **safety-critical** | A hidden or wrongly cleared alarm can harm a patient |
| Alarm limits (thresholds) | Safety-critical configuration | Tampering silences alarms |
| Staff accounts, sessions, MFA factors | Confidential — security | Account takeover |
| Audit trail | Confidential — integrity-critical | Accountability, forensics |
| Application keys (data encryption, audit HMAC, pseudonym, device master), DB password, Supabase secret key | Secret | Compromise breaks all other controls |
| Reports (CSV) | Restricted (identified) / Internal (de-identified) | Bulk disclosure |

## 3. Security objectives

1. Only authenticated, active staff with a live session access data; each role sees the minimum it needs.
2. Alarms cannot be cleared by user action while their condition persists; alarm limits change only by authorised clinicians and every change is audited.
3. Health data is encrypted in transit everywhere and at rest (volume + field level for free text).
4. Every security-relevant action is attributable and the audit trail is tamper-evident.
5. The service degrades safely (polling when Realtime fails, connection-lost alarms when devices go silent).
6. Staff privacy rights (access, correction, erasure, consent withdrawal) are supported.

## 4. Threats (STRIDE) and mitigations

| # | Threat | Mitigations | Residual risk |
| --- | --- | --- | --- |
| S1 | Credential stuffing / brute force on sign-in | API-proxied login, per-account lockout, per-IP limit, random failure delay, uniform errors, MFA (required for admin actions) | Low |
| S2 | Stolen access token reused | Short-lived JWT, server session registry (logout/idle/absolute/role-change revocation enforced in API **and** RLS), sessionStorage scope, strict CSP | Medium until browser-side token encryption / DPoP |
| S3 | Session obtained directly from Supabase Auth, bypassing throttling | API and RLS accept only sessions registered by `/auth/login` | Low |
| S4 | Forged device readings | HMAC per device, timestamp window, nonce replay table | Low |
| T1 | SQL injection | Bound parameters, allowlisted dynamic fragments, tests | Low |
| T2 | Tampering with alarm limits or acknowledging to silence alarms | Physician-only limits with validation; acknowledgement never changes alarm state; audit | Low |
| T3 | Audit log modification | Append-only grants, HMAC chain, integrity verification UI | Low (DB superuser could still delete; detected) |
| T4 | Malicious upload | Image allowlist, magic bytes, size limit, re-encode, private bucket, server-chosen names | Low |
| R1 | User denies having acknowledged/changed something | Audit with actor, IP, user agent, request id, HMAC chain | Low |
| I1 | Broken object-level authorization (IDOR) | `ensure_patient_access`, report kind filter, RLS | Low |
| I2 | Over-exposure to technical staff | Biomed sees device state only; break-glass for single patient, time-limited, audited | Low |
| I3 | XSS leading to data theft | React escaping, no raw HTML, CSP `script-src 'self'`, no inline scripts | Low |
| I4 | PHI in URLs/logs | POST search, fragment tokens removed, audit detail filter | Low |
| I5 | Bulk export / harvesting | Pagination caps, rate limits, de-identification, audit | Medium (insider) |
| D1 | API flooding | Body limits, DB-backed rate limits on sensitive endpoints, Vercel edge | Medium (no WAF rules configured) |
| D2 | Realtime outage hides changes | Automatic polling fallback with visible indicator | Low |
| D3 | Monitor silently disconnected | Watchdog connection-lost critical alarm + simulated pager | Low |
| E1 | Privilege escalation via role change | Admin + AAL2 only, no self-change, last-admin guard, sessions revoked on role change | Low |
| E2 | Compromise of service keys | Keys only in server env, validated length; rotation process **not yet defined** | Medium |

## 5. Compliance scope identified

- Health data handling (HIPAA-style safeguards: access control, audit, integrity, transmission security) — surveyed in SD Elements.
- MDS2 disclosure — not completed (simulation, not a regulated device).
- Personal data/privacy (staff): notice, consent, access, correction, erasure, restriction, retention, record of processing.

Jurisdiction and data residency must be confirmed before any real deployment.

## 6. Open items

SAST, DAST, penetration test, independent code review, backup/restore, network restrictions for the database, SIEM/log drains, key-management process, incident response and breach-notification procedures, environment separation, MDS2 — tracked as *Incomplete* in SD Elements and in [controls.md](controls.md).
