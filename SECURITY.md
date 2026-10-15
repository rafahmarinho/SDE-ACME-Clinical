# Security policy

## Reporting a vulnerability

Please report suspected vulnerabilities privately to **security@acme-clinical.example** (placeholder — replace with a monitored mailbox before going live; also published at `/.well-known/security.txt`). Include steps to reproduce and the affected URL or file. Do not access patient data beyond what is needed to demonstrate the issue. We aim to acknowledge reports within 3 working days.

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.x | Yes |

## How ACME Clinical protects data

| Area | Controls |
| --- | --- |
| Identity | Supabase Auth, invitation-only accounts, password policy (12+ chars, 4 classes, common-password check), TOTP MFA; AAL2 required for admin actions |
| Sign-in | Proxied through the API: account lockout (5 failures / 15 min), per-IP limit, uniform errors, random delay, previous sign-in notice |
| Sessions | Server registry: idle 15 min, absolute 12 h, logout and role changes revoke immediately in the API and in Row Level Security; max 3 concurrent sessions; tokens in sessionStorage, never cookies |
| Authorization | Central role → permission matrix, object-level checks, break-glass access with justification and review, separation of duties |
| Input/output | Strict Pydantic models (unknown fields rejected), bound SQL parameters, control/bidi character filtering, Latin-only names, body and query limits, CSV formula neutralisation |
| Data | TLS everywhere; AES-256-GCM for clinical notes; private storage buckets; HMAC pseudonyms for de-identified reports; retention purge |
| Audit | HMAC-SHA256 chained, append-only audit log with integrity verification |
| Web | CSP (`script-src 'self'`), HSTS, X-Frame-Options DENY, nosniff, Referrer-Policy no-referrer, COOP, no server banners, `Cache-Control: no-store` |
| Devices | HMAC-signed ingestion with timestamp window and nonce replay protection |
| Supply chain | Latest stable dependencies pinned by lockfiles; `pip-audit` and `pnpm audit` in CI |

Details: [docs/security/threat-model.md](docs/security/threat-model.md) and [docs/security/controls.md](docs/security/controls.md).

## Key rotation

Generate new values with `python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"`.

- `DATA_ENCRYPTION_KEY`: decrypt and re-encrypt `notes.body_encrypted` with the new key during a maintenance window (ciphertexts are versioned `v1:`).
- `AUDIT_HMAC_KEY`: export the audit log and its verification result, then rotate; the chain restarts from the next record.
- `PSEUDONYM_KEY`: rotating changes pseudonyms in future de-identified reports.
- `DEVICE_MASTER_KEY`: re-provision device secrets.
- `acme_api` password and Supabase secret key: rotate in Supabase, update Vercel environment variables, redeploy.
