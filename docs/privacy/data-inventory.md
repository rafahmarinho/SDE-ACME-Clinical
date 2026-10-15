# Data inventory and record of processing activities

ACME Clinical (demonstration). All patient data is fictional. This record describes what the system is designed to process.

## Categories and classification

| Category | Data elements | Classification | Where stored | Purpose | Retention |
| --- | --- | --- | --- | --- | --- |
| Patient identity | first/last name, MRN, date of birth, sex, bed | Health data (restricted) | `patients` | Identify the patient at the bedside and in records | While admitted; demo reset |
| Clinical record | diagnosis, attending physician, acuity, allergies, code status | Health data (restricted) | `patients` | Safe care decisions | While admitted |
| Clinical notes | free text, category, author, time | Health data (restricted) — **AES-256-GCM encrypted** | `notes` | Care documentation and handover | While admitted |
| Vital signs and alarms | HR, SpO₂, RR, BP, quality, alarms, acknowledgements | Health data (restricted) | `vital_readings`, `alarms` | Monitoring and alarm response | Readings: `DATA_RETENTION_DAYS` (7 days, automatic purge) |
| Alarm limits | per-patient thresholds | Clinical configuration | `thresholds` | Alarm generation | While admitted |
| Staff identity | name, work e-mail, role, job title, phone, photo | Personal data (confidential) | `profiles`, Supabase Auth, private `avatars` bucket | Access control, attribution of clinical actions | While employed; erasure on request (anonymisation) |
| Staff preferences | landing page, density, alarm sound, 3D view | Personal data (internal) | `profiles.preferences` | Usability | With the account |
| Security data | sign-in times and IPs, sessions, user agent, audit trail, failed-login counters | Personal data (confidential) | `user_sessions`, `profiles`, `audit_log`, `auth_throttle` | Security, accountability, patient safety | Sessions purged 30 days after expiry; audit trail kept (legal obligation) |
| Consent and privacy requests | notice version/time, requests | Personal data | `profiles`, `privacy_requests` | Demonstrate lawful processing | With the account |
| Reports | CSV extracts (identified or de-identified) | Restricted / internal | private `reports` bucket | Shift handover, quality review | Until demo reset |
| Device data | monitor ids, battery, connectivity, maintenance | Operational | `monitors`, `maintenance_records` | Equipment safety | Lifetime of device |

Not collected: home address, national identifiers, insurance or payment data, biometrics.

## Recipients

- Clinical staff by role (see README › Roles). Biomedical technicians see no patient identity or vitals unless they use time-limited break-glass access.
- Processors: Supabase (database, authentication, storage, realtime), Vercel (hosting). Simulated recipients: pager gateway, EHR gateway, privacy office (integration outbox only).

## Data subject rights (staff)

| Right | How |
| --- | --- |
| Information | Privacy notice at first sign-in (versioned) |
| Access / portability | Settings › Privacy › Download my data (JSON) |
| Rectification | Profile page; administrators for role/e-mail |
| Erasure | Settings › Privacy › Request deletion → Team › Remove personal data (anonymisation) |
| Withdraw consent | Settings › Privacy › Withdraw consent |
| Restriction (patients) | Administrators restrict a patient from secondary use; excluded from de-identified reports |

## Safeguards

TLS everywhere, RLS on all tables, least-privilege database role, field-level encryption of notes, keyed pseudonymisation (HMAC-SHA256) for secondary use, retention purge, HMAC-chained audit trail, MFA for administrative actions.
