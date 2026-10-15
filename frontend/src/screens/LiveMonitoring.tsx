import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BatteryLow, Pause, Play, SkipForward, WifiOff } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { Vital } from '../components/BedCard'
import { EcgCanvas } from '../components/EcgCanvas'
import { EmptyState, ErrorState, LoadingCards, SeverityBadge } from '../components/ui'
import { useAuth } from '../hooks/useAuth'
import { useToast } from '../hooks/useToast'
import { ALARM_LABELS, relative, sensorLabel } from '../lib/format'
import { errorMessage } from '../services/api'
import { Api } from '../services/endpoints'
import type { BedState } from '../services/types'

function MonitorTile({ bed }: { bed: BedState }) {
  const types = new Set((bed.alarms ?? []).map((a) => a.type))
  const offline = bed.connection === 'offline'
  return (
    <div className={`monitor-tile${bed.top_severity === 'critical' ? ' sev-critical' : ''}`}>
      <div className="monitor-tile-head">
        <div>
          <strong>{bed.label}</strong>{' '}
          {bed.patient_id ? (
            <Link to={`/patients/${bed.patient_id}`}>
              {bed.first_name} {bed.last_name}
            </Link>
          ) : (
            <span className="muted">No patient</span>
          )}
          <div className="muted small">
            <span className="mono">{bed.monitor_id}</span> · {offline ? 'offline' : sensorLabel(bed.sensor_status)} · {relative(bed.recorded_at)}
          </div>
        </div>
        <div className="row" style={{ gap: 6 }}>
          {offline && <WifiOff size={16} color="var(--offline)" />}
          {bed.battery_pct !== null && bed.battery_pct < 20 && (
            <span className="row small" style={{ gap: 3, color: 'var(--critical)' }}>
              <BatteryLow size={16} />
              {Math.round(bed.battery_pct)}%
            </span>
          )}
          {bed.active_alarms > 0 ? <SeverityBadge severity={bed.top_severity} /> : <span className="badge badge-ok">Stable</span>}
        </div>
      </div>
      <div className="monitor-tile-body">
        <div className="ecg-wrap">{bed.monitor_id && <EcgCanvas monitorId={bed.monitor_id} />}</div>
        <div className="tile-numerics">
          <Vital label="HR" value={offline ? null : bed.heart_rate} unit="bpm" cls="hr" alert={types.has('hr_high') || types.has('hr_low')} />
          <Vital label="SpO₂" value={offline ? null : bed.spo2} unit="%" cls="spo2" alert={types.has('spo2_low')} />
          <Vital label="RR" value={offline ? null : bed.resp_rate} unit="/min" cls="rr" alert={types.has('rr_high') || types.has('rr_low')} />
          <div className="vital">
            <span className="vital-label">NIBP</span>
            <span className="vital-value num bp small">{!offline && bed.systolic ? `${bed.systolic}/${bed.diastolic}` : '--/--'}</span>
            <span className="vital-unit">mmHg</span>
          </div>
        </div>
      </div>
      {(bed.alarms ?? []).length > 0 && (
        <div className="row small" style={{ padding: '8px 14px', borderTop: '1px solid var(--border)', gap: 6 }}>
          {(bed.alarms ?? []).map((a) => (
            <span key={a.id} className={`badge badge-${a.severity}`}>
              {ALARM_LABELS[a.type] ?? a.type}
              {a.acknowledged ? ' · ack' : ''}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

export default function LiveMonitoring() {
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [auto, setAuto] = useState(false)
  const [filter, setFilter] = useState<'all' | 'alarms'>('all')
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ['overview'], queryFn: Api.overview })
  const advance = useMutation({
    mutationFn: (source: 'manual' | 'auto') => Api.advance(1, source),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['overview'] }),
    onError: (err) => {
      setAuto(false)
      toast(errorMessage(err), 'error')
    },
  })

  // Demo clock: one simulated tick every 5 seconds while the page is visible.
  useEffect(() => {
    if (!auto) return
    const id = window.setInterval(() => {
      if (document.visibilityState === 'visible') advance.mutate('auto')
    }, 5000)
    return () => window.clearInterval(id)
  }, [auto])

  const monitored = (data?.beds ?? []).filter((b) => b.monitor_id && b.occupied)
  const shown = filter === 'alarms' ? monitored.filter((b) => b.active_alarms > 0) : monitored

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Live monitoring</h1>
          <p>Central station view of every monitored bed. ECG waveforms are synthetic.</p>
        </div>
        <div className="row">
          <select className="select" style={{ width: 'auto' }} value={filter} onChange={(e) => setFilter(e.target.value as 'all' | 'alarms')} aria-label="Filter">
            <option value="all">All monitored beds</option>
            <option value="alarms">Beds with alarms</option>
          </select>
          {can('simulation:advance') && (
            <>
              <button className="btn" onClick={() => advance.mutate('manual')} disabled={advance.isPending}>
                <SkipForward size={16} /> Advance 5 s
              </button>
              <button className={`btn ${auto ? 'btn-danger' : 'btn-primary'}`} onClick={() => setAuto((a) => !a)}>
                {auto ? <Pause size={16} /> : <Play size={16} />} {auto ? 'Pause simulation' : 'Run simulation'}
              </button>
            </>
          )}
        </div>
      </div>
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && <LoadingCards count={6} height={190} />}
      {data && shown.length === 0 && <EmptyState title={filter === 'alarms' ? 'No beds with active alarms' : 'No monitored beds'} />}
      <div className="monitor-tiles">
        {shown.map((bed) => (
          <MonitorTile key={bed.bed_id} bed={bed} />
        ))}
      </div>
    </>
  )
}
