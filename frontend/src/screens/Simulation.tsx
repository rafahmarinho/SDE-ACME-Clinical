import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FastForward, RotateCcw, SkipForward, Zap } from 'lucide-react'
import { useState } from 'react'
import { Battery } from './Devices'
import { ConfirmDialog, EmptyState, ErrorState, Skeleton } from '../components/ui'
import { useAuth } from '../hooks/useAuth'
import { useToast } from '../hooks/useToast'
import { fmtTime, relative, sensorLabel } from '../lib/format'
import { ApiError, errorMessage } from '../services/api'
import { Api } from '../services/endpoints'
import type { Scenario } from '../services/types'

const EVENT_KINDS = ['all', 'alarm_raised', 'alarm_escalated', 'alarm_resolved', 'alarm_acknowledged', 'scenario_change', 'preset', 'advance', 'assignment', 'maintenance', 'integration', 'thresholds', 'reset']
const KIND_BADGE: Record<string, string> = {
  alarm_raised: 'badge-critical',
  alarm_escalated: 'badge-critical',
  alarm_resolved: 'badge-ok',
  alarm_acknowledged: 'badge-warning',
  scenario_change: 'badge-advisory',
  preset: 'badge-advisory',
  integration: 'badge-navy',
  reset: 'badge-navy',
}

export default function Simulation() {
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [kind, setKind] = useState('all')
  const [monitor, setMonitor] = useState('')
  const [resetting, setResetting] = useState(false)
  const state = useQuery({ queryKey: ['simState'], queryFn: Api.simState })
  const outbox = useQuery({ queryKey: ['outbox'], queryFn: Api.outbox })
  const events = useInfiniteQuery({
    queryKey: ['events', kind, monitor],
    queryFn: ({ pageParam }) => Api.events({ kind, monitor_id: monitor || undefined, before_id: pageParam ?? undefined, limit: 40 }),
    initialPageParam: null as number | null,
    getNextPageParam: (last) => last.next_before_id,
  })
  const refreshAll = () => ['simState', 'events', 'overview', 'alarms', 'devices', 'outbox'].forEach((k) => void queryClient.invalidateQueries({ queryKey: [k] }))
  const onError = (err: unknown) =>
    toast(err instanceof ApiError && err.code === 'mfa_required_admin' ? `${err.message}` : errorMessage(err), 'error')

  const advance = useMutation({
    mutationFn: (steps: number) => Api.advance(steps),
    onSuccess: (r) => (toast(`Advanced to t=${r.tick}. ${r.alarms_raised ?? 0} new alarm(s).`, 'success'), refreshAll()),
    onError,
  })
  const scenario = useMutation({
    mutationFn: ({ id, value }: { id: string; value: Scenario }) => Api.setScenario(id, value),
    onSuccess: () => (toast('Scenario updated. Advance the simulation to see its effect.', 'success'), refreshAll()),
    onError,
  })
  const preset = useMutation({
    mutationFn: Api.applyPreset,
    onSuccess: () => (toast('Preset applied.', 'success'), refreshAll()),
    onError,
  })
  const reset = useMutation({
    mutationFn: Api.resetDemo,
    onSuccess: (r) => (toast(r.message, 'success'), setResetting(false), queryClient.invalidateQueries()),
    onError: (err) => (setResetting(false), onError(err)),
  })

  if (state.error) return <ErrorState error={state.error} onRetry={() => void state.refetch()} />
  const s = state.data

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Simulation console</h1>
          <p>Drive the simulated monitors: choose scenarios, advance time, inspect events and reset the demo.</p>
        </div>
        <div className="row">
          {s && (
            <span className="pill num">
              t={s.state.tick} · {fmtTime(s.state.sim_time)} · {s.state.tick_seconds}s per tick
            </span>
          )}
          <button className="btn" onClick={() => advance.mutate(1)} disabled={advance.isPending}>
            <SkipForward size={16} /> +1 tick
          </button>
          <button className="btn" onClick={() => advance.mutate(12)} disabled={advance.isPending}>
            <FastForward size={16} /> +1 min
          </button>
          <button className="btn btn-primary" onClick={() => advance.mutate(60)} disabled={advance.isPending}>
            <FastForward size={16} /> +5 min
          </button>
          {s?.can_reset && (
            <button className="btn btn-danger" onClick={() => setResetting(true)}>
              <RotateCcw size={16} /> Reset demo data
            </button>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Scenario presets</h2>
        </div>
        <div className="card-body grid grid-3">
          {s?.presets.map((p) => (
            <button key={p.id} className="btn" style={{ justifyContent: 'flex-start', textAlign: 'left', whiteSpace: 'normal', padding: 14 }} onClick={() => preset.mutate(p.id)} disabled={preset.isPending || !can('simulation:control')}>
              <Zap size={18} />
              <span>
                <strong>{p.label}</strong>
                <span className="muted small" style={{ display: 'block', fontWeight: 400 }}>
                  {p.description}
                </span>
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="split">
        <div className="card">
          <div className="card-head">
            <h2>Monitors</h2>
          </div>
          {!s && <Skeleton height={300} />}
          {s && (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Monitor</th>
                    <th>Bed</th>
                    <th>Scenario</th>
                    <th>Battery</th>
                    <th>Signal</th>
                  </tr>
                </thead>
                <tbody>
                  {s.monitors.map((m) => (
                    <tr key={m.id}>
                      <td className="mono">{m.id}</td>
                      <td>{m.bed_id ?? <span className="muted">—</span>}</td>
                      <td>
                        <select className="select" value={m.scenario} onChange={(e) => scenario.mutate({ id: m.id, value: e.target.value as Scenario })} disabled={!can('simulation:control')} aria-label={`Scenario for ${m.id}`}>
                          {s.scenarios.map((sc) => (
                            <option key={sc.id} value={sc.id}>
                              {sc.label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <Battery pct={m.battery_pct} />
                      </td>
                      <td className="small">
                        {m.connection === 'offline' ? <span style={{ color: 'var(--offline)' }}>Offline · {relative(m.last_seen_at)}</span> : sensorLabel(m.sensor_status)}
                        {m.status !== 'active' && <div className="muted">{m.status}</div>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        <div className="card">
          <div className="card-head">
            <h2>Integration outbox</h2>
            <span className="muted small">Simulated pager / EHR / privacy office</span>
          </div>
          {outbox.data?.items.length === 0 && <EmptyState title="Nothing sent yet" />}
          <div className="card-body timeline" style={{ maxHeight: 420, overflow: 'auto' }}>
            {outbox.data?.items.map((o) => (
              <div key={o.id} className="timeline-item">
                <div className="small muted">{fmtTime(o.created_at)}</div>
                <div className="small">
                  <span className="badge badge-navy">{o.channel}</span> {o.subject}
                  <div className="muted">
                    to {o.recipient} · {o.status}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Event inspector</h2>
          <div className="toolbar">
            <select className="select" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Event type">
              {EVENT_KINDS.map((k) => (
                <option key={k} value={k}>
                  {k === 'all' ? 'All events' : k.replace(/_/g, ' ')}
                </option>
              ))}
            </select>
            <select className="select" value={monitor} onChange={(e) => setMonitor(e.target.value)} aria-label="Monitor">
              <option value="">All monitors</option>
              {s?.monitors.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.id}
                </option>
              ))}
            </select>
          </div>
        </div>
        {events.error && <ErrorState error={events.error} />}
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Tick</th>
                <th>Time</th>
                <th>Event</th>
                <th>Monitor</th>
                <th>Details</th>
                <th>By</th>
              </tr>
            </thead>
            <tbody>
              {events.data?.pages.flatMap((p) => p.items).map((e) => (
                <tr key={e.id}>
                  <td className="num mono">{e.tick}</td>
                  <td className="small num">{fmtTime(e.occurred_at)}</td>
                  <td>
                    <span className={`badge ${KIND_BADGE[e.kind] ?? 'badge-muted'}`}>{e.kind.replace(/_/g, ' ')}</span>
                  </td>
                  <td className="mono">{e.monitor_id ?? '—'}</td>
                  <td className="small">{e.message}</td>
                  <td className="small muted">{e.actor ?? 'simulator'}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {events.data && events.data.pages[0]?.items.length === 0 && <EmptyState title="No events match" />}
        </div>
        {events.hasNextPage && (
          <div className="card-body">
            <button className="btn" onClick={() => void events.fetchNextPage()} disabled={events.isFetchingNextPage}>
              Load older events
            </button>
          </div>
        )}
      </div>

      {resetting && (
        <ConfirmDialog
          title="Reset all demo data?"
          body={
            <>
              Patients, monitors, readings, alarms, notes, maintenance records and reports go back to their initial state. Staff accounts and
              the audit trail are kept. <strong>This cannot be undone.</strong>
            </>
          }
          confirmLabel="Reset demo data"
          danger
          requireText="RESET"
          busy={reset.isPending}
          onConfirm={() => reset.mutate()}
          onClose={() => setResetting(false)}
        />
      )}
    </>
  )
}
