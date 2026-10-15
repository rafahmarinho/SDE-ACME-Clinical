import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Link2, Unlink, Wrench } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { AckButton, AlarmStateBadge } from '../components/AlarmRow'
import { ConfirmDialog, EmptyState, ErrorState, Field, Modal, SeverityBadge, Skeleton } from '../components/ui'
import { useAuth } from '../hooks/useAuth'
import { useToast } from '../hooks/useToast'
import { ALARM_LABELS, fmtDate, fmtDateTime, MAINTENANCE_LABELS, relative, sensorLabel } from '../lib/format'
import { errorMessage } from '../services/api'
import { Api } from '../services/endpoints'
import type { MaintenanceRecord } from '../services/types'
import { Battery } from './Devices'

function TicketActions({ ticket }: { ticket: MaintenanceRecord }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [resolution, setResolution] = useState('')
  const [completing, setCompleting] = useState(false)
  const update = useMutation({
    mutationFn: (status: string) => Api.updateTicket(ticket.id, { status, resolution: resolution.trim() }),
    onSuccess: () => {
      toast('Maintenance record updated.', 'success')
      setCompleting(false)
      ;['device', 'devices', 'maintenance'].forEach((k) => void queryClient.invalidateQueries({ queryKey: [k] }))
    },
    onError: (err) => toast(errorMessage(err), 'error'),
  })
  if (ticket.status === 'completed') return null
  return (
    <div className="row">
      {ticket.status === 'open' && (
        <button className="btn btn-sm" onClick={() => update.mutate('in_progress')} disabled={update.isPending}>
          Start work
        </button>
      )}
      <button className="btn btn-sm btn-primary" onClick={() => setCompleting(true)}>
        Complete
      </button>
      {completing && (
        <Modal
          title="Complete maintenance"
          onClose={() => setCompleting(false)}
          footer={
            <>
              <button className="btn" onClick={() => setCompleting(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" disabled={!resolution.trim() || update.isPending} onClick={() => update.mutate('completed')}>
                Mark completed
              </button>
            </>
          }
        >
          <Field label="Work performed" htmlFor="resolution" hint="Required. Recorded in the device history.">
            <input id="resolution" className="input" value={resolution} onChange={(e) => setResolution(e.target.value)} maxLength={200} autoComplete="off" />
          </Field>
        </Modal>
      )}
    </div>
  )
}

export default function DeviceDetail() {
  const { id = '' } = useParams()
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [assigning, setAssigning] = useState(false)
  const [bedId, setBedId] = useState('')
  const [unassigning, setUnassigning] = useState(false)
  const [ticketOpen, setTicketOpen] = useState(false)
  const [ticket, setTicket] = useState({ type: can('maintenance:manage') ? 'inspection' : 'issue_report', description: '' })
  const device = useQuery({ queryKey: ['device', id], queryFn: () => Api.device(id) })
  const beds = useQuery({ queryKey: ['beds'], queryFn: Api.beds, enabled: assigning })

  const refresh = () => ['device', 'devices', 'overview', 'beds', 'maintenance'].forEach((k) => void queryClient.invalidateQueries({ queryKey: [k] }))
  const onError = (err: unknown) => toast(errorMessage(err), 'error')
  const assign = useMutation({
    mutationFn: () => Api.assign(id, bedId),
    onSuccess: () => (toast(`${id} assigned to ${bedId}.`, 'success'), setAssigning(false), refresh()),
    onError,
  })
  const unassign = useMutation({
    mutationFn: () => Api.unassign(id),
    onSuccess: () => (toast(`${id} removed from its bed.`, 'success'), setUnassigning(false), refresh()),
    onError,
  })
  const setStatus = useMutation({
    mutationFn: (status: string) => Api.updateDevice(id, { status }),
    onSuccess: () => (toast('Device status updated.', 'success'), refresh()),
    onError,
  })
  const openTicket = useMutation({
    mutationFn: () => Api.openTicket(id, { type: ticket.type, description: ticket.description.trim() }),
    onSuccess: () => (toast('Maintenance record opened.', 'success'), setTicketOpen(false), setTicket({ ...ticket, description: '' }), refresh()),
    onError,
  })

  if (device.error) return <ErrorState error={device.error} onRetry={() => void device.refetch()} />
  if (!device.data) return <Skeleton height={400} />
  const m = device.data

  return (
    <>
      <Link to="/devices" className="row small">
        <ArrowLeft size={16} /> All devices
      </Link>
      <div className="page-head">
        <div>
          <h1 className="mono" style={{ fontSize: '1.6rem' }}>
            {m.id}
          </h1>
          <p>
            {m.model} · serial {m.serial_number} · firmware {m.firmware}
          </p>
        </div>
        <div className="row">
          {can('devices:assign') &&
            (m.bed_id ? (
              <button className="btn" onClick={() => setUnassigning(true)}>
                <Unlink size={16} /> Remove from {m.bed_id}
              </button>
            ) : (
              <button className="btn btn-primary" onClick={() => setAssigning(true)} disabled={m.status === 'maintenance' || m.status === 'retired'}>
                <Link2 size={16} /> Assign to bed
              </button>
            ))}
          <button className="btn" onClick={() => setTicketOpen(true)}>
            <Wrench size={16} /> {can('maintenance:manage') ? 'Log maintenance' : 'Report a problem'}
          </button>
        </div>
      </div>

      <div className="grid grid-4">
        <div className="card kpi">
          <span className="kpi-label">Bed</span>
          <span className="kpi-value">{m.bed_id ?? '—'}</span>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Battery</span>
          <span className="kpi-value">
            <Battery pct={m.battery_pct} />
          </span>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Connection</span>
          <span className="kpi-value" style={{ fontSize: '1.4rem' }}>
            {m.connection === 'online' ? 'Online' : 'Offline'}
          </span>
          <span className="muted small">Last data {relative(m.last_seen_at)}</span>
        </div>
        <div className="card kpi">
          <span className="kpi-label">Sensors</span>
          <span className="kpi-value" style={{ fontSize: '1.4rem' }}>
            {sensorLabel(m.sensor_status)}
          </span>
        </div>
      </div>

      <div className="split">
        <div className="stack">
          <div className="card">
            <div className="card-head">
              <h2>Maintenance history</h2>
              <span className="muted small">
                Last service {fmtDate(m.last_maintenance_at)} · next due {fmtDate(m.next_maintenance_due)}
              </span>
            </div>
            {m.maintenance.length === 0 && <EmptyState title="No maintenance records" />}
            {m.maintenance.length > 0 && (
              <table className="table">
                <thead>
                  <tr>
                    <th>Opened</th>
                    <th>Type</th>
                    <th>Details</th>
                    <th>Status</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {m.maintenance.map((t) => (
                    <tr key={t.id}>
                      <td className="small">
                        {fmtDateTime(t.opened_at)}
                        <div className="muted">{t.opened_by_name}</div>
                      </td>
                      <td>{MAINTENANCE_LABELS[t.type]}</td>
                      <td className="small">
                        {t.description}
                        {t.resolution && <div className="muted">Resolution: {t.resolution}</div>}
                      </td>
                      <td>
                        <span className={`badge ${t.status === 'completed' ? 'badge-ok' : t.status === 'open' ? 'badge-warning' : 'badge-advisory'}`}>{t.status.replace('_', ' ')}</span>
                        {t.completed_at && <div className="muted small">{fmtDate(t.completed_at)}</div>}
                      </td>
                      <td>{can('maintenance:manage') && <TicketActions ticket={t} />}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="card">
            <div className="card-head">
              <h2>Technical alarms</h2>
            </div>
            {m.technical_alarms.length === 0 && <EmptyState title="No technical alarms" />}
            <div className="card-body timeline">
              {m.technical_alarms.map((a) => (
                <div key={a.id} className="timeline-item">
                  <div className="small muted">{relative(a.raised_at)}</div>
                  <div className="row">
                    <SeverityBadge severity={a.severity} />
                    <strong>{ALARM_LABELS[a.type]}</strong>
                    <AlarmStateBadge alarm={a} />
                    {a.state === 'active' && !a.acknowledged_at && can('alarms:ack_technical') && <AckButton alarm={{ ...a, bed_id: m.bed_id }} />}
                    <span className="small muted" style={{ flexBasis: '100%' }}>
                      {a.message}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="stack">
          {can('devices:manage') && (
            <div className="card card-pad stack">
              <h2>Status</h2>
              <select className="select" value={m.status} onChange={(e) => setStatus.mutate(e.target.value)} disabled={setStatus.isPending} aria-label="Device status">
                <option value="active">Active (on a bed)</option>
                <option value="standby">Standby</option>
                <option value="maintenance">In maintenance</option>
                <option value="retired">Retired</option>
              </select>
              <p className="muted small">Remove the monitor from its bed before taking it out of service.</p>
            </div>
          )}
          <div className="card">
            <div className="card-head">
              <h2>Assignment history</h2>
            </div>
            <div className="card-body timeline">
              {m.assignments.length === 0 && <span className="muted">Never assigned.</span>}
              {m.assignments.map((a, i) => (
                <div key={i} className="timeline-item">
                  <strong>{a.bed_id}</strong>
                  <div className="small">
                    {fmtDateTime(a.assigned_at)} → {a.unassigned_at ? fmtDateTime(a.unassigned_at) : <span className="badge badge-ok">current</span>}
                    <div className="muted">
                      {a.assigned_by ? `by ${a.assigned_by}` : ''}
                      {a.unassigned_by ? ` · removed by ${a.unassigned_by}` : ''}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {assigning && (
        <Modal
          title={`Assign ${m.id} to a bed`}
          onClose={() => setAssigning(false)}
          footer={
            <>
              <button className="btn" onClick={() => setAssigning(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" disabled={!bedId || assign.isPending} onClick={() => assign.mutate()}>
                Assign
              </button>
            </>
          }
        >
          <Field label="Bed" htmlFor="bed" hint="Beds that already have a monitor cannot be selected.">
            <select id="bed" className="select" value={bedId} onChange={(e) => setBedId(e.target.value)}>
              <option value="">Choose a bed…</option>
              {beds.data?.items.map((b) => (
                <option key={b.id} value={b.id} disabled={!!b.monitor_id}>
                  {b.label} · {b.room} · {b.monitor_id ? `has ${b.monitor_id}` : b.patient_name ?? (b.occupied ? 'occupied' : 'empty')}
                </option>
              ))}
            </select>
          </Field>
        </Modal>
      )}
      {unassigning && (
        <ConfirmDialog
          title={`Remove ${m.id} from ${m.bed_id}?`}
          body="The patient in this bed will no longer be monitored by this device and its active alarms will be closed."
          confirmLabel="Remove monitor"
          danger
          busy={unassign.isPending}
          onConfirm={() => unassign.mutate()}
          onClose={() => setUnassigning(false)}
        />
      )}
      {ticketOpen && (
        <Modal
          title={can('maintenance:manage') ? 'Log maintenance' : 'Report a problem'}
          onClose={() => setTicketOpen(false)}
          footer={
            <>
              <button className="btn" onClick={() => setTicketOpen(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" disabled={!ticket.description.trim() || openTicket.isPending} onClick={() => openTicket.mutate()}>
                Save
              </button>
            </>
          }
        >
          {can('maintenance:manage') && (
            <Field label="Type" htmlFor="ticket-type">
              <select id="ticket-type" className="select" value={ticket.type} onChange={(e) => setTicket({ ...ticket, type: e.target.value })}>
                {Object.entries(MAINTENANCE_LABELS).map(([k, v]) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
              </select>
            </Field>
          )}
          <Field label="Description" htmlFor="ticket-desc">
            <textarea id="ticket-desc" className="textarea" value={ticket.description} onChange={(e) => setTicket({ ...ticket, description: e.target.value })} maxLength={1000} />
          </Field>
        </Modal>
      )}
    </>
  )
}
