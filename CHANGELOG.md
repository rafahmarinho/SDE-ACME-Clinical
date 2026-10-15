# Changelog

## 1.0.0 — 2026-10-12

Initial release of ACME Clinical (demonstration).

### Added
- Ward overview with KPIs, bed cards and an interactive 3D ward (beds, monitors coloured by alarm state, staff avatars walking to beds that need attention).
- Patients: search and filters, chart with live vitals, sweeping synthetic ECG, trends with alarm-limit bands, encrypted clinical notes, patient-specific alarm limits, editable clinical details.
- Live monitoring central station with ECG for every monitored bed and a demo clock (run/pause, advance).
- Alarms: active/resolved/needs-attention views, filters, acknowledgement with note (acknowledgement never clears an ongoing condition), simulated pager for critical alarms.
- Devices: 10 simulated monitors, monitor-to-bed assignment with history, status, battery/connectivity/sensor state, maintenance records and issue reports.
- Reports generated in Python (shift summary, alarm log, device status, patient vitals) with CSV download, SHA-256 integrity check and de-identification.
- Simulation console: scenarios (normal, low SpO₂, weak battery, sensor issue, lost connection), presets, advance, event inspector, integration outbox, demo reset.
- Team management (invitations, roles, deactivation, anonymisation, privacy requests) and audit log with integrity verification and break-glass review.
- Profile (photo upload), settings (preferences, password, TOTP MFA, sessions, privacy: export, deletion request, consent withdrawal, system security view).
- Security controls described in SECURITY.md; Supabase migration with RLS and least-privilege API role; 87 backend and 10 frontend automated tests; CI workflow.
