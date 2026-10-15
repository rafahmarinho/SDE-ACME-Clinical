import { BatteryLow, BellRing, WifiOff } from 'lucide-react'
import { Link } from 'react-router'
import { sensorLabel } from '../lib/format'
import type { BedState } from '../services/types'
import { SeverityBadge } from './ui'

export function Vital({ label, value, unit, cls, alert, big }: { label: string; value: string | number | null; unit: string; cls: string; alert?: boolean; big?: boolean }) {
  return (
    <div className={`vital${big ? ' vital-big' : ''}`}>
      <span className="vital-label">{label}</span>
      <span className={`vital-value num ${cls}${alert ? ' alert' : ''}`}>{value ?? '--'}</span>
      <span className="vital-unit">{unit}</span>
    </div>
  )
}

export function VitalsRow({ bed, big }: { bed: Pick<BedState, 'heart_rate' | 'spo2' | 'resp_rate' | 'systolic' | 'diastolic' | 'alarms'>; big?: boolean }) {
  const types = new Set((bed.alarms ?? []).map((a) => a.type))
  return (
    <div className="vitals">
      <Vital label="HR" value={bed.heart_rate} unit="bpm" cls="hr" alert={types.has('hr_high') || types.has('hr_low')} big={big} />
      <Vital label="SpO₂" value={bed.spo2} unit="%" cls="spo2" alert={types.has('spo2_low')} big={big} />
      <Vital label="RR" value={bed.resp_rate} unit="/min" cls="rr" alert={types.has('rr_high') || types.has('rr_low')} big={big} />
      <div className="vital">
        <span className="vital-label">NIBP</span>
        <span className={`vital-value num bp small${types.has('bp_high') || types.has('bp_low') ? ' alert' : ''}`}>
          {bed.systolic ? `${bed.systolic}/${bed.diastolic}` : '--/--'}
        </span>
        <span className="vital-unit">mmHg</span>
      </div>
    </div>
  )
}

export function BedCard({ bed, showClinical }: { bed: BedState; showClinical: boolean }) {
  const offline = bed.connection === 'offline'
  const cls = !bed.occupied ? 'empty' : bed.top_severity ? `sev-${bed.top_severity}` : offline ? 'offline' : ''
  const name = bed.first_name ? `${bed.first_name} ${bed.last_name}` : bed.occupied ? 'Occupied bed' : 'Empty bed'
  const to = showClinical && bed.patient_id ? `/patients/${bed.patient_id}` : bed.monitor_id ? `/devices/${bed.monitor_id}` : '#'
  return (
    <Link to={to} className={`bed ${cls}`} aria-label={`${bed.label}: ${name}`}>
      <div className="bed-head">
        <div>
          <div className="bed-label">
            {bed.label} · {bed.room}
          </div>
          <div className="bed-name">{name}</div>
        </div>
        {bed.active_alarms > 0 ? <SeverityBadge severity={bed.top_severity} /> : bed.monitor_id ? <span className="badge badge-ok">Stable</span> : null}
      </div>
      {bed.monitor_id && showClinical && bed.occupied && <VitalsRow bed={bed} />}
      <div className="row small muted" style={{ gap: 12 }}>
        {bed.monitor_id ? <span className="mono">{bed.monitor_id}</span> : <span>No monitor assigned</span>}
        {offline && (
          <span className="row" style={{ gap: 4, color: 'var(--offline)' }}>
            <WifiOff size={14} /> Offline
          </span>
        )}
        {bed.battery_pct !== null && bed.battery_pct < 20 && (
          <span className="row" style={{ gap: 4, color: 'var(--critical)' }}>
            <BatteryLow size={14} /> {Math.round(bed.battery_pct)}%
          </span>
        )}
        {bed.sensor_status && bed.sensor_status !== 'ok' && <span style={{ color: 'var(--warning)' }}>{sensorLabel(bed.sensor_status)}</span>}
        {bed.unacknowledged > 0 && (
          <span className="row" style={{ gap: 4, color: 'var(--critical)' }}>
            <BellRing size={14} /> {bed.unacknowledged} unacknowledged
          </span>
        )}
      </div>
    </Link>
  )
}
