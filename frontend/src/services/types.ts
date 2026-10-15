export type Role = 'nurse' | 'physician' | 'biomed' | 'admin'
export type Severity = 'critical' | 'warning' | 'advisory'
export type Scenario = 'normal' | 'low_spo2' | 'weak_battery' | 'sensor_issue' | 'lost_connection'
export type VitalKey = 'heart_rate' | 'spo2' | 'resp_rate' | 'systolic' | 'diastolic'

export interface Preferences {
  landing_page: string
  alarm_sound: boolean
  density: 'comfortable' | 'compact'
  ward_view: 'grid' | '3d'
  critical_banner: boolean
}

export interface Me {
  id: string
  email: string
  full_name: string
  role: Role
  job_title: string | null
  phone: string | null
  unit: string
  created_at: string
  avatar_url: string | null
  preferences: Preferences
  consent: { accepted_at: string | null; version: string | null; current_version: string; required: boolean }
  previous_sign_in: { at: string | null; ip: string | null }
  permissions: string[]
  session: { aal: string; mfa_enrolled: boolean; created_at?: string; expires_at?: string; idle_timeout_seconds?: number }
  privacy_requests: { kind: string; status: string; created_at: string }[]
}

export interface AlarmBrief {
  id: string
  type: string
  severity: Severity
  message: string
  acknowledged: boolean
  category: 'physiological' | 'technical'
}

export interface BedState {
  bed_id: string
  label: string
  room: string
  pos_x: number
  pos_z: number
  occupied: boolean
  patient_id: string | null
  first_name: string | null
  last_name: string | null
  acuity: string | null
  mrn: string | null
  code_status: string | null
  monitor_id: string | null
  monitor_status: string | null
  battery_pct: number | null
  connection: 'online' | 'offline' | null
  sensor_status: string | null
  scenario: Scenario | null
  last_seen_at: string | null
  heart_rate: number | null
  spo2: number | null
  resp_rate: number | null
  systolic: number | null
  diastolic: number | null
  recorded_at: string | null
  quality: string | null
  active_alarms: number
  unacknowledged: number
  top_severity: Severity | null
  alarms: AlarmBrief[] | null
}

export interface Overview {
  kpis: {
    patients: number
    monitored: number
    critical: number
    warnings: number
    unacknowledged: number
    offline: number
    low_battery: number
    maintenance_due: number
    open_tickets: number
  }
  beds: BedState[]
  simulation: { tick: number; sim_time: string; tick_seconds: number; last_advanced_at: string | null } | null
}

export interface PatientRow {
  id: string
  mrn: string
  first_name: string
  last_name: string
  date_of_birth: string
  sex: string
  bed_id: string | null
  status: string
  acuity: 'low' | 'medium' | 'high'
  diagnosis: string
  attending_physician: string
  admitted_at: string
  restricted: boolean
  monitor_id: string | null
  connection: string | null
  active_alarms: number
  top_severity: Severity | null
  heart_rate: number | null
  spo2: number | null
  resp_rate: number | null
  systolic: number | null
  diastolic: number | null
}

export interface Threshold {
  low: number | null
  high: number | null
  enabled: boolean
  source?: 'default' | 'patient'
}

export interface PatientDetail extends Omit<PatientRow, 'active_alarms' | 'top_severity' | 'heart_rate' | 'spo2' | 'resp_rate' | 'systolic' | 'diastolic'> {
  allergies: string
  code_status: string
  bed_label: string | null
  room: string | null
  monitor_model: string | null
  sensor_status: string | null
  battery_pct: number | null
  last_seen_at: string | null
  latest: Vital | null
  alarms: Alarm[]
  thresholds: Record<VitalKey, Threshold>
  emergency_access: { expires_at: string; reason: string } | null
}

export interface Vital {
  recorded_at: string
  heart_rate: number | null
  spo2: number | null
  resp_rate: number | null
  systolic: number | null
  diastolic: number | null
  quality: string
}

export interface Note {
  id: string
  category: string
  body: string
  created_at: string
  author: string
  author_role: Role | null
}

export interface Alarm {
  id: string
  monitor_id?: string
  bed_id?: string | null
  patient_id?: string | null
  patient_name?: string | null
  type: string
  category: 'physiological' | 'technical'
  severity: Severity
  message: string
  value?: number | null
  threshold?: number | null
  state: 'active' | 'resolved'
  raised_at: string
  last_seen_at?: string
  resolved_at?: string | null
  acknowledged_at: string | null
  acknowledged_by_name: string | null
  ack_note: string | null
  can_acknowledge?: boolean
}

export interface Monitor {
  id: string
  serial_number: string
  model: string
  firmware: string
  bed_id: string | null
  status: 'active' | 'standby' | 'maintenance' | 'retired'
  scenario: Scenario
  battery_pct: number
  connection: 'online' | 'offline'
  sensor_status: string
  last_seen_at: string | null
  last_maintenance_at: string | null
  next_maintenance_due: string | null
  open_tickets?: number
  technical_alarms?: number
}

export interface MaintenanceRecord {
  id: string
  monitor_id?: string
  bed_id?: string | null
  type: string
  status: 'open' | 'in_progress' | 'completed'
  description: string
  resolution: string | null
  opened_by_name: string | null
  completed_by_name: string | null
  opened_at: string
  completed_at: string | null
}

export interface MonitorDetail extends Omit<Monitor, 'technical_alarms'> {
  assignments: { bed_id: string; assigned_at: string; unassigned_at: string | null; assigned_by: string | null; unassigned_by: string | null }[]
  maintenance: MaintenanceRecord[]
  technical_alarms: Alarm[]
}

export interface Bed {
  id: string
  label: string
  room: string
  monitor_id: string | null
  occupied: boolean
  patient_name: string | null
}

export interface ReportSummary {
  id: string
  kind: string
  title: string
  params: { period_hours?: number; patient_id?: string | null }
  deidentified: boolean
  size_bytes: number
  row_count: number
  created_by_name: string | null
  created_at: string
}

export interface ReportDetail extends ReportSummary {
  sha256: string
  summary: Record<string, unknown> & { columns: string[]; preview: Record<string, unknown>[] }
}

export interface SimEvent {
  id: number
  tick: number
  occurred_at: string
  kind: string
  monitor_id: string | null
  message: string
  data: Record<string, unknown>
  actor: string | null
}

export interface SimState {
  state: { tick: number; sim_time: string; seed: number; tick_seconds: number; last_advanced_at: string | null }
  monitors: Pick<Monitor, 'id' | 'bed_id' | 'status' | 'scenario' | 'battery_pct' | 'connection' | 'sensor_status' | 'last_seen_at'>[]
  scenarios: { id: Scenario; label: string }[]
  presets: { id: string; label: string; description: string }[]
  can_reset: boolean
}

export interface TeamMember {
  id: string
  email: string
  full_name: string
  role: Role
  job_title: string | null
  phone: string | null
  active: boolean
  avatar_url: string | null
  last_sign_in_at: string | null
  created_at: string
  anonymized_at: string | null
  active_sessions: number
  is_self: boolean
}

export interface AuditEntry {
  id: number
  created_at: string
  actor_email: string | null
  actor_role: string | null
  action: string
  entity_type: string | null
  entity_id: string | null
  outcome: 'success' | 'failure' | 'denied'
  details: Record<string, unknown>
  ip: string | null
  request_id: string | null
}

export interface Paged<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}
