import { api } from './api'
import type {
  Alarm,
  AuditEntry,
  Bed,
  MaintenanceRecord,
  Me,
  Monitor,
  MonitorDetail,
  Note,
  Overview,
  Paged,
  PatientDetail,
  PatientRow,
  Preferences,
  ReportDetail,
  ReportSummary,
  Role,
  Scenario,
  SimEvent,
  SimState,
  TeamMember,
  Threshold,
  VitalKey,
  Vital,
} from './types'

const qs = (params: Record<string, string | number | undefined | null>) => {
  const search = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') search.set(k, String(v))
  const s = search.toString()
  return s ? `?${s}` : ''
}

export interface ThresholdItem {
  parameter: VitalKey
  low: number | null
  high: number | null
  enabled: boolean
}

export const Api = {
  // me / profile
  me: () => api<Me>('/me'),
  updateProfile: (body: { full_name: string; job_title: string; phone: string }) => api('/me', { method: 'PATCH', body }),
  updatePreferences: (body: Preferences) => api<Preferences>('/me/preferences', { method: 'PUT', body }),
  changePassword: (body: { current_password: string; new_password: string }) =>
    api<{ message: string }>('/me/password', { method: 'POST', body }),
  uploadAvatar: (file: File) => {
    const form = new FormData()
    form.append('file', file)
    return api<{ avatar_url: string }>('/me/avatar', { method: 'POST', form })
  },
  deleteAvatar: () => api('/me/avatar', { method: 'DELETE' }),
  acceptConsent: (version: string) => api('/me/consent', { method: 'POST', body: { version } }),
  withdrawConsent: () => api('/me/consent/withdraw', { method: 'POST' }),
  requestDeletion: (details: string) => api('/me/privacy-requests', { method: 'POST', body: { kind: 'deletion', details } }),
  sessions: () => api<{ items: { session_id: string; created_at: string; last_seen_at: string; ip: string | null; user_agent: string | null; current: boolean }[] }>('/me/sessions'),
  revokeOtherSessions: () => api<{ revoked: number }>('/me/sessions/revoke-others', { method: 'POST' }),
  passwordPolicy: () => api<{ password: { min_length: number }; idle_timeout_minutes: number }>('/auth/policy', { auth: false }),

  // ward
  overview: () => api<Overview>('/ward/overview'),
  ecg: (monitorId: string, seconds = 6) =>
    api<{ monitor_id: string; fs: number; status: string; samples: number[]; heart_rate: number | null; tick?: number }>(
      `/monitors/${encodeURIComponent(monitorId)}/ecg${qs({ seconds })}`,
    ),

  // patients
  searchPatients: (body: Record<string, unknown>) => api<Paged<PatientRow>>('/patients/search', { method: 'POST', body }),
  patient: (id: string) => api<PatientDetail>(`/patients/${encodeURIComponent(id)}`),
  updatePatient: (id: string, body: Record<string, string>) => api(`/patients/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
  setRestriction: (id: string, restricted: boolean) =>
    api(`/patients/${encodeURIComponent(id)}/restriction`, { method: 'PUT', body: { restricted } }),
  vitals: (id: string, minutes: number) => api<{ items: Vital[] }>(`/patients/${encodeURIComponent(id)}/vitals${qs({ minutes })}`),
  notes: (id: string) => api<{ items: Note[] }>(`/patients/${encodeURIComponent(id)}/notes`),
  addNote: (id: string, body: { category: string; body: string }) =>
    api<Note>(`/patients/${encodeURIComponent(id)}/notes`, { method: 'POST', body }),
  setPatientThresholds: (id: string, items: ThresholdItem[], reset: VitalKey[] = []) =>
    api<{ thresholds: Record<VitalKey, Threshold> }>(`/patients/${encodeURIComponent(id)}/thresholds`, {
      method: 'PUT',
      body: { items, reset_to_default: reset },
    }),
  emergencyAccess: (id: string, reason: string) =>
    api<{ expires_at: string }>(`/patients/${encodeURIComponent(id)}/emergency-access`, { method: 'POST', body: { reason } }),

  // alarms & thresholds
  alarms: (params: Record<string, string | number>) =>
    api<Paged<Alarm> & { counts: { active: number; critical: number; unacknowledged: number } }>(`/alarms${qs(params)}`),
  acknowledge: (id: string, note: string) =>
    api<{ state: string; message: string }>(`/alarms/${encodeURIComponent(id)}/acknowledge`, { method: 'POST', body: { note } }),
  thresholdDefaults: () =>
    api<{
      defaults: Record<VitalKey, Threshold>
      overrides: { id: string; first_name: string; last_name: string; bed_id: string | null; parameter: VitalKey; low: number | null; high: number | null; enabled: boolean }[]
      can_edit_defaults: boolean
      can_edit_patient: boolean
    }>('/thresholds/defaults'),
  setThresholdDefaults: (items: ThresholdItem[]) => api('/thresholds/defaults', { method: 'PUT', body: { items } }),

  // devices
  devices: (params: Record<string, string>) => api<{ items: Monitor[] }>(`/devices${qs(params)}`),
  device: (id: string) => api<MonitorDetail>(`/devices/${encodeURIComponent(id)}`),
  beds: () => api<{ items: Bed[] }>('/beds'),
  assign: (id: string, bed_id: string) => api(`/devices/${encodeURIComponent(id)}/assign`, { method: 'POST', body: { bed_id } }),
  unassign: (id: string) => api(`/devices/${encodeURIComponent(id)}/unassign`, { method: 'POST' }),
  updateDevice: (id: string, body: { status?: string; next_maintenance_due?: string }) =>
    api(`/devices/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
  openTicket: (id: string, body: { type: string; description: string }) =>
    api(`/devices/${encodeURIComponent(id)}/maintenance`, { method: 'POST', body }),
  maintenance: (status: string) => api<{ items: MaintenanceRecord[] }>(`/maintenance${qs({ status })}`),
  updateTicket: (id: string, body: { status: string; resolution: string }) =>
    api(`/maintenance/${encodeURIComponent(id)}`, { method: 'PATCH', body }),

  // reports
  reports: () => api<{ items: ReportSummary[]; kinds: string[] }>('/reports'),
  report: (id: string) => api<ReportDetail>(`/reports/${encodeURIComponent(id)}`),
  createReport: (body: { kind: string; period_hours: number; patient_id?: string | null; deidentified: boolean }) =>
    api<{ id: string; title: string; row_count: number }>('/reports', { method: 'POST', body }),

  // simulation
  simState: () => api<SimState>('/simulation/state'),
  advance: (steps: number, source: 'manual' | 'auto' = 'manual') =>
    api<{ skipped: boolean; tick?: number; alarms_raised?: number }>('/simulation/advance', { method: 'POST', body: { steps, source } }),
  setScenario: (monitorId: string, scenario: Scenario) =>
    api(`/simulation/monitors/${encodeURIComponent(monitorId)}/scenario`, { method: 'PUT', body: { scenario } }),
  applyPreset: (preset: string) => api(`/simulation/presets/${encodeURIComponent(preset)}`, { method: 'POST' }),
  events: (params: Record<string, string | number | undefined>) =>
    api<{ items: SimEvent[]; next_before_id: number | null }>(`/simulation/events${qs(params)}`),
  outbox: () => api<{ items: { id: number; channel: string; recipient: string; subject: string; status: string; created_at: string }[] }>('/simulation/outbox'),
  resetDemo: () => api<{ message: string }>('/simulation/reset', { method: 'POST', body: { confirm: 'RESET' } }),

  // team & admin
  team: (params: Record<string, string>) => api<{ items: TeamMember[] }>(`/team${qs(params)}`),
  invite: (body: { email: string; full_name: string; role: Role; job_title: string }) =>
    api('/team/invite', { method: 'POST', body }),
  updateMember: (id: string, body: { role?: Role; active?: boolean }) => api(`/team/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
  anonymize: (id: string) => api(`/team/${encodeURIComponent(id)}/anonymize`, { method: 'POST' }),
  privacyRequests: () =>
    api<{ items: { id: string; kind: string; status: string; details: string | null; created_at: string; full_name: string; email: string; user_id: string }[] }>(
      '/team/privacy-requests',
    ),
  decidePrivacyRequest: (id: string, status: 'completed' | 'rejected') =>
    api(`/team/privacy-requests/${encodeURIComponent(id)}`, { method: 'PATCH', body: { status } }),
  audit: (params: Record<string, string | number>) => api<Paged<AuditEntry>>(`/admin/audit${qs(params)}`),
  verifyAudit: () => api<{ valid: boolean; checked: number; broken_at: number | null }>('/admin/audit/verify'),
  emergencyLog: () =>
    api<{ items: { id: string; reason: string; granted_at: string; expires_at: string; reviewed_at: string | null; user_name: string; role: string; patient_name: string; bed_id: string | null }[] }>(
      '/admin/emergency-access',
    ),
  reviewEmergency: (id: string) => api(`/admin/emergency-access/${encodeURIComponent(id)}/review`, { method: 'POST' }),
  securitySettings: () => api<Record<string, unknown>>('/admin/security-settings'),
}
