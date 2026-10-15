import type { Role, Scenario, Severity } from '../services/types'

const dateTime = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })
const timeFmt = new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const dateFmt = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })

export const fmtDateTime = (value: string | null | undefined) => (value ? dateTime.format(new Date(value)) : '—')
export const fmtTime = (value: string | null | undefined) => (value ? timeFmt.format(new Date(value)) : '—')
export const fmtDate = (value: string | null | undefined) => (value ? dateFmt.format(new Date(value)) : '—')

export function age(dob: string): number {
  const d = new Date(dob)
  const now = new Date()
  let years = now.getFullYear() - d.getFullYear()
  if (now.getMonth() < d.getMonth() || (now.getMonth() === d.getMonth() && now.getDate() < d.getDate())) years -= 1
  return years
}

export function relative(value: string | null | undefined): string {
  if (!value) return '—'
  const seconds = Math.round((Date.now() - new Date(value).getTime()) / 1000)
  // The simulated clock can run slightly ahead of the wall clock after fast-forwarding.
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (Math.abs(minutes) < 60) return minutes > 0 ? `${minutes} min ago` : `in ${-minutes} min`
  const hours = Math.round(minutes / 60)
  if (Math.abs(hours) < 24) return hours > 0 ? `${hours} h ago` : `in ${-hours} h`
  return fmtDateTime(value)
}

export const ROLE_LABELS: Record<Role, string> = {
  nurse: 'Nurse',
  physician: 'Physician',
  biomed: 'Biomedical technician',
  admin: 'Administrator',
}

export const SCENARIO_LABELS: Record<Scenario, string> = {
  normal: 'Normal readings',
  low_spo2: 'Low oxygen saturation',
  weak_battery: 'Weak battery',
  sensor_issue: 'Sensor issue',
  lost_connection: 'Lost connection',
}

export const ALARM_LABELS: Record<string, string> = {
  hr_high: 'Heart rate high',
  hr_low: 'Heart rate low',
  spo2_low: 'SpO₂ low',
  rr_high: 'Resp. rate high',
  rr_low: 'Resp. rate low',
  bp_high: 'Blood pressure high',
  bp_low: 'Blood pressure low',
  battery_low: 'Battery low',
  sensor_issue: 'Sensor issue',
  connection_lost: 'Connection lost',
}

export const PARAM_LABELS = {
  heart_rate: { label: 'Heart rate', unit: 'bpm', short: 'HR' },
  spo2: { label: 'Oxygen saturation', unit: '%', short: 'SpO₂' },
  resp_rate: { label: 'Respiratory rate', unit: '/min', short: 'RR' },
  systolic: { label: 'Systolic BP', unit: 'mmHg', short: 'SYS' },
  diastolic: { label: 'Diastolic BP', unit: 'mmHg', short: 'DIA' },
} as const

export const MAINTENANCE_LABELS: Record<string, string> = {
  inspection: 'Inspection',
  battery_replacement: 'Battery replacement',
  sensor_replacement: 'Sensor replacement',
  repair: 'Repair',
  calibration: 'Calibration',
  issue_report: 'Issue report',
}

export const REPORT_LABELS: Record<string, string> = {
  shift_summary: 'Shift summary',
  alarm_log: 'Alarm log',
  device_maintenance: 'Device & maintenance status',
  patient_vitals: 'Patient vitals trend',
}

export function severityClass(severity: Severity | null | undefined): string {
  return severity ? `badge-${severity}` : 'badge-ok'
}

export const sensorLabel = (status: string | null | undefined) =>
  status === 'spo2_probe_off' ? 'SpO₂ probe off' : status === 'ecg_leads_off' ? 'ECG leads off' : 'Sensors OK'

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join('')
}

export function bytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}
