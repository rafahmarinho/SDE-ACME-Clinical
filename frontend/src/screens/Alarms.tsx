import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { AckButton, AlarmStateBadge } from '../components/AlarmRow'
import { EmptyState, ErrorState, Pagination, SeverityBadge, Skeleton } from '../components/ui'
import { ALARM_LABELS, fmtTime, relative } from '../lib/format'
import { Api } from '../services/endpoints'

const TABS = [
  { id: 'attention', label: 'Needs attention' },
  { id: 'active', label: 'Active' },
  { id: 'resolved', label: 'Resolved' },
  { id: 'all', label: 'All' },
] as const

export default function Alarms() {
  const [state, setState] = useState<(typeof TABS)[number]['id']>('attention')
  const [severity, setSeverity] = useState('all')
  const [category, setCategory] = useState('all')
  const [acknowledged, setAcknowledged] = useState('all')
  const [bed, setBed] = useState('')
  const [page, setPage] = useState(1)
  const params: Record<string, string | number> = { state, severity, category, acknowledged, page, page_size: 25 }
  if (bed) params.bed_id = bed
  const { data, error, isLoading, refetch } = useQuery({
    queryKey: ['alarms', params],
    queryFn: () => Api.alarms(params),
    placeholderData: keepPreviousData,
  })

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Alarms</h1>
          <p>Acknowledging records your response. An alarm only clears when its condition is no longer present.</p>
        </div>
        {data && (
          <div className="row">
            <span className="badge badge-critical">{data.counts.critical} critical active</span>
            <span className="badge badge-warning">{data.counts.active} active</span>
            <span className="badge badge-navy">{data.counts.unacknowledged} unacknowledged</span>
          </div>
        )}
      </div>
      <div className="card">
        <div className="tabs" role="tablist" style={{ padding: '0 12px' }}>
          {TABS.map((t) => (
            <button
              key={t.id}
              role="tab"
              aria-selected={state === t.id}
              className={state === t.id ? 'active' : ''}
              onClick={() => {
                setState(t.id)
                setPage(1)
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
        <div className="card-body toolbar">
          <select className="select" value={severity} onChange={(e) => (setSeverity(e.target.value), setPage(1))} aria-label="Severity">
            <option value="all">All severities</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
          </select>
          <select className="select" value={category} onChange={(e) => (setCategory(e.target.value), setPage(1))} aria-label="Category">
            <option value="all">Clinical and technical</option>
            <option value="physiological">Clinical (physiological)</option>
            <option value="technical">Technical</option>
          </select>
          <select className="select" value={acknowledged} onChange={(e) => (setAcknowledged(e.target.value), setPage(1))} aria-label="Acknowledgement">
            <option value="all">Acknowledged or not</option>
            <option value="no">Not acknowledged</option>
            <option value="yes">Acknowledged</option>
          </select>
          <select className="select" value={bed} onChange={(e) => (setBed(e.target.value), setPage(1))} aria-label="Bed">
            <option value="">All beds</option>
            {Array.from({ length: 12 }, (_, i) => `B${String(i + 1).padStart(2, '0')}`).map((b) => (
              <option key={b} value={b}>
                Bed {Number(b.slice(1))}
              </option>
            ))}
          </select>
        </div>
        {error && (
          <div className="card-body">
            <ErrorState error={error} onRetry={() => void refetch()} />
          </div>
        )}
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Raised</th>
                <th>Bed</th>
                <th>Alarm</th>
                <th>Details</th>
                <th>Status</th>
                <th>Response</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {isLoading &&
                Array.from({ length: 6 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={7}>
                      <Skeleton />
                    </td>
                  </tr>
                ))}
              {data?.items.map((a) => (
                <tr key={a.id}>
                  <td className="num small">
                    {fmtTime(a.raised_at)}
                    <div className="muted">{relative(a.raised_at)}</div>
                  </td>
                  <td>
                    <strong>{a.bed_id}</strong>
                    <div className="small">{a.patient_id && a.patient_name ? <Link to={`/patients/${a.patient_id}`}>{a.patient_name}</Link> : <span className="muted mono">{a.monitor_id}</span>}</div>
                  </td>
                  <td>
                    <div className="row" style={{ gap: 6 }}>
                      <SeverityBadge severity={a.severity} />
                      <strong>{ALARM_LABELS[a.type] ?? a.type}</strong>
                    </div>
                    <div className="muted small">{a.category === 'technical' ? 'Technical' : 'Clinical'}</div>
                  </td>
                  <td className="small">{a.message}</td>
                  <td>
                    <AlarmStateBadge alarm={a} />
                  </td>
                  <td className="small">
                    {a.acknowledged_at ? (
                      <>
                        {a.acknowledged_by_name}
                        <div className="muted">
                          {fmtTime(a.acknowledged_at)}
                          {a.ack_note ? ` · ${a.ack_note}` : ''}
                        </div>
                      </>
                    ) : (
                      <span className="muted">—</span>
                    )}
                  </td>
                  <td>{a.can_acknowledge && <AckButton alarm={a} />}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data && data.items.length === 0 && <EmptyState title="No alarms match these filters">Everything looks calm.</EmptyState>}
        </div>
        {data && <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={setPage} />}
      </div>
    </>
  )
}
