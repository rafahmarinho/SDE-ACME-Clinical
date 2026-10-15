import { useQuery } from '@tanstack/react-query'
import { BatteryFull, BatteryLow, BatteryMedium, Wifi, WifiOff } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { EmptyState, ErrorState, Skeleton } from '../components/ui'
import { fmtDate, MAINTENANCE_LABELS, relative, sensorLabel } from '../lib/format'
import { Api } from '../services/endpoints'

export function Battery({ pct }: { pct: number }) {
  const Icon = pct < 20 ? BatteryLow : pct < 60 ? BatteryMedium : BatteryFull
  const color = pct < 20 ? 'var(--critical)' : pct < 40 ? 'var(--warning)' : 'var(--ok)'
  return (
    <span className="row num" style={{ gap: 4, color, fontWeight: 650 }}>
      <Icon size={18} /> {Math.round(pct)}%
    </span>
  )
}

const STATUS_BADGE: Record<string, string> = { active: 'badge-ok', standby: 'badge-navy', maintenance: 'badge-warning', retired: 'badge-muted' }

export default function Devices() {
  const navigate = useNavigate()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('all')
  const [issue, setIssue] = useState('any')
  const params = { q, status, issue }
  const devices = useQuery({ queryKey: ['devices', params], queryFn: () => Api.devices(params) })
  const tickets = useQuery({ queryKey: ['maintenance', 'pending'], queryFn: () => Api.maintenance('pending') })

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Devices</h1>
          <p>Ten simulated bedside monitors: assignment, battery, connectivity and maintenance.</p>
        </div>
      </div>
      <div className="card">
        <div className="card-body toolbar">
          <input className="input" placeholder="Search by ID, serial, model or bed" value={q} onChange={(e) => setQ(e.target.value)} maxLength={100} aria-label="Search devices" style={{ minWidth: 280 }} />
          <select className="select" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
            <option value="all">All statuses</option>
            <option value="active">Active</option>
            <option value="standby">Standby</option>
            <option value="maintenance">In maintenance</option>
            <option value="retired">Retired</option>
          </select>
          <select className="select" value={issue} onChange={(e) => setIssue(e.target.value)} aria-label="Issues">
            <option value="any">Any condition</option>
            <option value="offline">Offline</option>
            <option value="low_battery">Low battery</option>
            <option value="sensor">Sensor problem</option>
            <option value="maintenance_due">Maintenance overdue</option>
          </select>
        </div>
        {devices.error && (
          <div className="card-body">
            <ErrorState error={devices.error} onRetry={() => void devices.refetch()} />
          </div>
        )}
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Monitor</th>
                <th>Bed</th>
                <th>Status</th>
                <th>Battery</th>
                <th>Connection</th>
                <th>Sensors</th>
                <th>Next maintenance</th>
                <th>Tickets</th>
              </tr>
            </thead>
            <tbody>
              {devices.isLoading &&
                Array.from({ length: 6 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={8}>
                      <Skeleton />
                    </td>
                  </tr>
                ))}
              {devices.data?.items.map((m) => {
                const overdue = m.next_maintenance_due && new Date(m.next_maintenance_due) < new Date()
                return (
                  <tr key={m.id} className="clickable" tabIndex={0} onClick={() => navigate(`/devices/${m.id}`)} onKeyDown={(e) => e.key === 'Enter' && navigate(`/devices/${m.id}`)}>
                    <td>
                      <strong className="mono">{m.id}</strong>
                      <div className="muted small">
                        {m.model} · fw {m.firmware}
                      </div>
                    </td>
                    <td>{m.bed_id ?? <span className="muted">Unassigned</span>}</td>
                    <td>
                      <span className={`badge ${STATUS_BADGE[m.status]}`}>{m.status}</span>
                    </td>
                    <td>
                      <Battery pct={m.battery_pct} />
                    </td>
                    <td>
                      {m.connection === 'online' ? (
                        <span className="row" style={{ gap: 4, color: 'var(--ok)' }}>
                          <Wifi size={16} /> Online
                        </span>
                      ) : (
                        <span className="row" style={{ gap: 4, color: 'var(--offline)' }}>
                          <WifiOff size={16} /> Offline · {relative(m.last_seen_at)}
                        </span>
                      )}
                    </td>
                    <td className="small">{sensorLabel(m.sensor_status)}</td>
                    <td className="small" style={{ color: overdue ? 'var(--critical)' : undefined }}>
                      {fmtDate(m.next_maintenance_due)}
                      {overdue ? ' · overdue' : ''}
                    </td>
                    <td>{m.open_tickets ? <span className="badge badge-warning">{m.open_tickets} open</span> : <span className="muted small">None</span>}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {devices.data?.items.length === 0 && <EmptyState title="No devices match these filters" />}
        </div>
      </div>
      <div className="card">
        <div className="card-head">
          <h2>Open maintenance work</h2>
        </div>
        {tickets.data?.items.length === 0 && <EmptyState title="No open maintenance work" />}
        {tickets.data && tickets.data.items.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Monitor</th>
                <th>Type</th>
                <th>Description</th>
                <th>Status</th>
                <th>Opened</th>
              </tr>
            </thead>
            <tbody>
              {tickets.data.items.map((t) => (
                <tr key={t.id}>
                  <td>
                    <Link to={`/devices/${t.monitor_id}`} className="mono">
                      {t.monitor_id}
                    </Link>
                  </td>
                  <td>{MAINTENANCE_LABELS[t.type]}</td>
                  <td className="small">{t.description}</td>
                  <td>
                    <span className={`badge ${t.status === 'open' ? 'badge-warning' : 'badge-advisory'}`}>{t.status.replace('_', ' ')}</span>
                  </td>
                  <td className="small muted">
                    {t.opened_by_name} · {relative(t.opened_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </>
  )
}
