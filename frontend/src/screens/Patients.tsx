import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router'
import { EmptyState, ErrorState, Pagination, SeverityBadge, Skeleton } from '../components/ui'
import { age, fmtDateTime } from '../lib/format'
import { Api } from '../services/endpoints'

interface Filters {
  q: string
  status: string
  acuity: string
  alarm: string
  monitored: string
  sort: string
  page: number
}

const INITIAL: Filters = { q: '', status: 'admitted', acuity: 'all', alarm: 'any', monitored: 'any', sort: 'bed', page: 1 }

export default function Patients() {
  const navigate = useNavigate()
  const [filters, setFilters] = useState<Filters>(INITIAL)
  const [text, setText] = useState('')

  // Debounce the free-text search; it is sent in a POST body, never in the URL.
  useEffect(() => {
    const t = window.setTimeout(() => setFilters((f) => (f.q === text ? f : { ...f, q: text, page: 1 })), 300)
    return () => window.clearTimeout(t)
  }, [text])

  const { data, error, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['patients', filters],
    queryFn: () => Api.searchPatients({ ...filters, page_size: 25 }),
    placeholderData: keepPreviousData,
  })
  const set = (patch: Partial<Filters>) => setFilters((f) => ({ ...f, ...patch, page: patch.page ?? 1 }))

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Patients</h1>
          <p>Search by name, record number or bed. Results update live.</p>
        </div>
        {isFetching && !isLoading && <span className="spinner" aria-label="Refreshing" />}
      </div>
      <div className="card">
        <div className="card-body toolbar">
          <div className="input-group" style={{ minWidth: 280, flex: 1 }}>
            <Search size={16} style={{ position: 'absolute', left: 12, top: 12, color: 'var(--muted)' }} />
            <input
              className="input"
              style={{ paddingLeft: 36 }}
              placeholder="Search patients"
              value={text}
              onChange={(e) => setText(e.target.value)}
              maxLength={200}
              autoComplete="off"
              aria-label="Search patients"
            />
          </div>
          <select className="select" value={filters.status} onChange={(e) => set({ status: e.target.value })} aria-label="Status">
            <option value="admitted">Admitted</option>
            <option value="discharged">Discharged</option>
            <option value="all">All statuses</option>
          </select>
          <select className="select" value={filters.acuity} onChange={(e) => set({ acuity: e.target.value })} aria-label="Acuity">
            <option value="all">Any acuity</option>
            <option value="high">High acuity</option>
            <option value="medium">Medium acuity</option>
            <option value="low">Low acuity</option>
          </select>
          <select className="select" value={filters.alarm} onChange={(e) => set({ alarm: e.target.value })} aria-label="Alarms">
            <option value="any">Any alarm state</option>
            <option value="active">With active alarms</option>
            <option value="none">Without alarms</option>
          </select>
          <select className="select" value={filters.monitored} onChange={(e) => set({ monitored: e.target.value })} aria-label="Monitoring">
            <option value="any">Monitored or not</option>
            <option value="yes">On a monitor</option>
            <option value="no">Not monitored</option>
          </select>
          <select className="select" value={filters.sort} onChange={(e) => set({ sort: e.target.value })} aria-label="Sort">
            <option value="bed">Sort by bed</option>
            <option value="name">Sort by name</option>
            <option value="acuity">Sort by acuity</option>
            <option value="admitted">Newest admissions</option>
          </select>
          {(text || JSON.stringify({ ...filters, q: '' }) !== JSON.stringify({ ...INITIAL, q: '' })) && (
            <button
              className="btn btn-ghost"
              onClick={() => {
                setText('')
                setFilters(INITIAL)
              }}
            >
              Clear filters
            </button>
          )}
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
                <th>Bed</th>
                <th>Patient</th>
                <th>Diagnosis</th>
                <th>Acuity</th>
                <th className="num">HR</th>
                <th className="num">SpO₂</th>
                <th className="num">RR</th>
                <th className="num">BP</th>
                <th>Alarms</th>
                <th>Admitted</th>
              </tr>
            </thead>
            <tbody>
              {isLoading &&
                Array.from({ length: 8 }, (_, i) => (
                  <tr key={i}>
                    <td colSpan={10}>
                      <Skeleton />
                    </td>
                  </tr>
                ))}
              {data?.items.map((p) => (
                <tr key={p.id} className="clickable" onClick={() => navigate(`/patients/${p.id}`)} tabIndex={0} onKeyDown={(e) => e.key === 'Enter' && navigate(`/patients/${p.id}`)}>
                  <td>
                    <strong>{p.bed_id ?? '—'}</strong>
                  </td>
                  <td>
                    <div style={{ fontWeight: 650 }}>
                      {p.last_name}, {p.first_name}
                    </div>
                    <div className="muted small">
                      {p.mrn} · {age(p.date_of_birth)} y · {p.sex}
                    </div>
                  </td>
                  <td className="small">{p.diagnosis}</td>
                  <td>
                    <span className={`badge ${p.acuity === 'high' ? 'badge-critical' : p.acuity === 'medium' ? 'badge-warning' : 'badge-ok'}`}>{p.acuity}</span>
                  </td>
                  <td className="num hr" style={{ fontWeight: 700, fontSize: '1.1rem' }}>
                    {p.heart_rate ?? '--'}
                  </td>
                  <td className="num spo2" style={{ fontWeight: 700, fontSize: '1.1rem' }}>
                    {p.spo2 ?? '--'}
                  </td>
                  <td className="num rr" style={{ fontWeight: 700 }}>
                    {p.resp_rate ?? '--'}
                  </td>
                  <td className="num bp" style={{ fontWeight: 700 }}>
                    {p.systolic ? `${p.systolic}/${p.diastolic}` : '--'}
                  </td>
                  <td>{p.active_alarms > 0 ? <SeverityBadge severity={p.top_severity} /> : <span className="muted small">None</span>}</td>
                  <td className="small muted">{fmtDateTime(p.admitted_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data && data.items.length === 0 && <EmptyState title="No patients match these filters">Try a different name, record number or bed.</EmptyState>}
        </div>
        {data && <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPage={(page) => set({ page })} />}
      </div>
    </>
  )
}
