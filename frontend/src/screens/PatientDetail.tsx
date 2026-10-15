import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, Lock, Pencil, ShieldAlert } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { Link, useParams } from 'react-router'
import { AlarmLine } from '../components/AlarmRow'
import { VitalsRow } from '../components/BedCard'
import { EcgCanvas } from '../components/EcgCanvas'
import { ThresholdForm, ThresholdTable } from '../components/ThresholdEditor'
import { TrendChart } from '../components/TrendChart'
import { EmptyState, ErrorState, Field, Modal, Skeleton, Spinner } from '../components/ui'
import { useAuth } from '../hooks/useAuth'
import { useToast } from '../hooks/useToast'
import { age, fmtDate, fmtDateTime, fmtTime, relative, ROLE_LABELS, sensorLabel } from '../lib/format'
import { ApiError, errorMessage } from '../services/api'
import { Api } from '../services/endpoints'
import type { PatientDetail as Detail } from '../services/types'

function EmergencyAccess({ patientId, onGranted }: { patientId: string; onGranted: () => void }) {
  const toast = useToast()
  const [reason, setReason] = useState('')
  const mutation = useMutation({
    mutationFn: () => Api.emergencyAccess(patientId, reason.trim()),
    onSuccess: (r) => {
      toast(`Emergency access granted until ${fmtTime(r.expires_at)}. This access is logged and reviewed.`, 'success')
      onGranted()
    },
    onError: (err) => toast(errorMessage(err), 'error'),
  })
  return (
    <div className="card card-pad stack" style={{ maxWidth: 640 }}>
      <div className="row">
        <Lock size={20} />
        <h2>Clinical record restricted</h2>
      </div>
      <p className="muted">
        Your role does not include access to patient charts. In an emergency you can open this record for a limited time. You must give a
        reason; the access is recorded, reported to the privacy office and reviewed by an administrator.
      </p>
      <Field label="Reason for emergency access" htmlFor="reason" hint="At least 15 characters.">
        <textarea id="reason" className="textarea" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} autoComplete="off" />
      </Field>
      <div>
        <button className="btn btn-danger" disabled={reason.trim().length < 15 || mutation.isPending} onClick={() => mutation.mutate()}>
          <ShieldAlert size={16} /> Break glass: open record
        </button>
      </div>
    </div>
  )
}

function EditPatient({ patient, onClose }: { patient: Detail; onClose: () => void }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [form, setForm] = useState({
    diagnosis: patient.diagnosis,
    attending_physician: patient.attending_physician,
    acuity: patient.acuity,
    allergies: patient.allergies,
    code_status: patient.code_status,
  })
  const mutation = useMutation({
    mutationFn: () => Api.updatePatient(patient.id, form),
    onSuccess: () => {
      toast('Patient details updated.', 'success')
      void queryClient.invalidateQueries({ queryKey: ['patient', patient.id] })
      onClose()
    },
    onError: (err) => toast(errorMessage(err), 'error'),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    mutation.mutate()
  }
  return (
    <Modal title="Edit clinical details" onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        <Field label="Diagnosis" htmlFor="dx">
          <input id="dx" className="input" value={form.diagnosis} onChange={(e) => setForm({ ...form, diagnosis: e.target.value })} maxLength={200} required />
        </Field>
        <Field label="Attending physician" htmlFor="doc">
          <input id="doc" className="input" value={form.attending_physician} onChange={(e) => setForm({ ...form, attending_physician: e.target.value })} maxLength={120} required />
        </Field>
        <div className="grid grid-2">
          <Field label="Acuity" htmlFor="acuity">
            <select id="acuity" className="select" value={form.acuity} onChange={(e) => setForm({ ...form, acuity: e.target.value as Detail['acuity'] })}>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </Field>
          <Field label="Code status" htmlFor="code">
            <select id="code" className="select" value={form.code_status} onChange={(e) => setForm({ ...form, code_status: e.target.value })}>
              {['Full code', 'DNR', 'DNI', 'DNR/DNI', 'Comfort care'].map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </Field>
        </div>
        <Field label="Allergies" htmlFor="allergies">
          <input id="allergies" className="input" value={form.allergies} onChange={(e) => setForm({ ...form, allergies: e.target.value })} maxLength={200} required />
        </Field>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={mutation.isPending}>
            {mutation.isPending ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

function Notes({ patientId }: { patientId: string }) {
  const { can, me } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [body, setBody] = useState('')
  const [category, setCategory] = useState(me?.role === 'physician' ? 'physician' : 'nursing')
  const notes = useQuery({ queryKey: ['notes', patientId], queryFn: () => Api.notes(patientId) })
  const mutation = useMutation({
    mutationFn: () => Api.addNote(patientId, { category, body: body.trim() }),
    onSuccess: () => {
      setBody('')
      toast('Note saved.', 'success')
      void queryClient.invalidateQueries({ queryKey: ['notes', patientId] })
    },
    onError: (err) => toast(errorMessage(err), 'error'),
  })
  return (
    <div className="card">
      <div className="card-head">
        <h2>Clinical notes</h2>
        <span className="muted small">Encrypted at rest</span>
      </div>
      <div className="card-body stack">
        {can('notes:create') && (
          <form
            className="stack"
            onSubmit={(e) => {
              e.preventDefault()
              mutation.mutate()
            }}
          >
            <textarea className="textarea" placeholder="Add a note…" value={body} onChange={(e) => setBody(e.target.value)} maxLength={4000} autoComplete="off" aria-label="Note" />
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <select className="select" style={{ width: 'auto' }} value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Note type">
                <option value="nursing">Nursing</option>
                {me?.role === 'physician' && <option value="physician">Physician</option>}
                <option value="handover">Handover</option>
                <option value="device">Device</option>
              </select>
              <button className="btn btn-primary" disabled={!body.trim() || mutation.isPending}>
                {mutation.isPending ? 'Saving…' : 'Add note'}
              </button>
            </div>
          </form>
        )}
        {notes.isLoading && <Spinner />}
        {notes.error && <ErrorState error={notes.error} />}
        {notes.data?.items.length === 0 && <EmptyState title="No notes yet" />}
        <div className="timeline">
          {notes.data?.items.map((n) => (
            <div key={n.id} className="timeline-item">
              <div className="small muted">
                {fmtDateTime(n.created_at)}
                <div>
                  <span className="badge badge-navy">{n.category}</span>
                </div>
              </div>
              <div>
                <div style={{ whiteSpace: 'pre-wrap' }}>{n.body}</div>
                <div className="small muted">
                  {n.author}
                  {n.author_role ? ` · ${ROLE_LABELS[n.author_role]}` : ''}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default function PatientDetail() {
  const { id = '' } = useParams()
  const { can } = useAuth()
  const toast = useToast()
  const queryClient = useQueryClient()
  const [minutes, setMinutes] = useState(30)
  const [editing, setEditing] = useState(false)
  const [editingLimits, setEditingLimits] = useState(false)
  const patient = useQuery({ queryKey: ['patient', id], queryFn: () => Api.patient(id), retry: (n, err) => !(err instanceof ApiError && err.status < 500) && n < 2 })
  const vitals = useQuery({ queryKey: ['vitals', id, minutes], queryFn: () => Api.vitals(id, minutes), enabled: patient.isSuccess })
  const limits = useMutation({
    mutationFn: ({ items, reset }: { items: Parameters<typeof Api.setPatientThresholds>[1]; reset: Parameters<typeof Api.setPatientThresholds>[2] }) =>
      Api.setPatientThresholds(id, items, reset),
    onSuccess: () => {
      toast('Alarm limits updated. They apply from the next reading.', 'success')
      setEditingLimits(false)
      void queryClient.invalidateQueries({ queryKey: ['patient', id] })
    },
    onError: (err) => toast(errorMessage(err), 'error'),
  })
  const restrict = useMutation({
    mutationFn: (restricted: boolean) => Api.setRestriction(id, restricted),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['patient', id] }),
    onError: (err) => toast(errorMessage(err), 'error'),
  })

  if (patient.error instanceof ApiError && patient.error.status === 403 && can('emergency:request')) {
    return (
      <>
        <Link to="/" className="row small">
          <ArrowLeft size={16} /> Back to ward
        </Link>
        <EmergencyAccess patientId={id} onGranted={() => void patient.refetch()} />
      </>
    )
  }
  if (patient.error) return <ErrorState error={patient.error} onRetry={() => void patient.refetch()} />
  if (patient.isLoading || !patient.data) {
    return (
      <div className="stack">
        <Skeleton height={40} width={320} />
        <Skeleton height={220} />
        <Skeleton height={300} />
      </div>
    )
  }
  const p = patient.data
  const items = vitals.data?.items ?? []
  const times = items.map((v) => v.recorded_at)
  const activeAlarms = p.alarms.filter((a) => a.state === 'active')
  const recentAlarms = p.alarms.filter((a) => a.state !== 'active')
  const bed = {
    heart_rate: p.latest?.heart_rate ?? null,
    spo2: p.latest?.spo2 ?? null,
    resp_rate: p.latest?.resp_rate ?? null,
    systolic: p.latest?.systolic ?? null,
    diastolic: p.latest?.diastolic ?? null,
    alarms: activeAlarms.map((a) => ({ id: a.id, type: a.type, severity: a.severity, message: a.message, acknowledged: !!a.acknowledged_at, category: a.category })),
  }

  return (
    <>
      <Link to="/patients" className="row small">
        <ArrowLeft size={16} /> All patients
      </Link>
      {p.emergency_access && (
        <div className="alert alert-warning">
          <ShieldAlert size={18} /> Emergency access active until {fmtTime(p.emergency_access.expires_at)}. Everything you view is recorded.
        </div>
      )}
      <div className="page-head">
        <div>
          <h1>
            {p.last_name}, {p.first_name}
          </h1>
          <p>
            {p.mrn} · {age(p.date_of_birth)} years ({fmtDate(p.date_of_birth)}) · {p.sex} · {p.bed_label ?? 'No bed'} {p.room ? `· Room ${p.room}` : ''}
          </p>
        </div>
        <div className="row">
          {p.restricted && <span className="badge badge-navy">Secondary use restricted</span>}
          <span className="badge badge-navy">{p.code_status}</span>
          {can('patients:restrict') && (
            <button className="btn" onClick={() => restrict.mutate(!p.restricted)} disabled={restrict.isPending}>
              {p.restricted ? 'Lift restriction' : 'Restrict processing'}
            </button>
          )}
          {can('patients:edit') && (
            <button className="btn" onClick={() => setEditing(true)}>
              <Pencil size={16} /> Edit details
            </button>
          )}
        </div>
      </div>

      <div className="split">
        <div className="stack">
          <div className="card">
            <div className="card-head">
              <h2>Live vital signs</h2>
              <span className="muted small">
                {p.monitor_id ? `${p.monitor_id} · ${p.monitor_model} · ${p.connection === 'offline' ? 'OFFLINE' : sensorLabel(p.sensor_status)} · battery ${Math.round(p.battery_pct ?? 0)}%` : 'No monitor assigned'}
                {p.latest && ` · updated ${relative(p.latest.recorded_at)}`}
              </span>
            </div>
            <div className="card-body stack">
              {p.monitor_id && <EcgCanvas monitorId={p.monitor_id} height={120} />}
              <VitalsRow bed={bed} big />
            </div>
          </div>

          <div className="card">
            <div className="card-head">
              <h2>Trends</h2>
              <select className="select" style={{ width: 'auto' }} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} aria-label="Time range">
                <option value={15}>Last 15 minutes</option>
                <option value={30}>Last 30 minutes</option>
                <option value={60}>Last hour</option>
                <option value={240}>Last 4 hours</option>
              </select>
            </div>
            <div className="card-body grid grid-2">
              {vitals.isLoading && <Skeleton height={160} />}
              {vitals.data && items.length === 0 && <EmptyState title="No readings in this period" />}
              {items.length > 0 && (
                <>
                  <div>
                    <strong className="small hr">Heart rate (bpm)</strong>
                    <TrendChart times={times} min={30} max={170} low={p.thresholds.heart_rate.low} high={p.thresholds.heart_rate.high} series={[{ key: 'hr', label: 'HR', color: '#0f7b4f', values: items.map((v) => v.heart_rate) }]} />
                  </div>
                  <div>
                    <strong className="small spo2">SpO₂ (%)</strong>
                    <TrendChart times={times} min={75} max={100} low={p.thresholds.spo2.low} series={[{ key: 'spo2', label: 'SpO2', color: '#1d5fbf', values: items.map((v) => v.spo2) }]} />
                  </div>
                  <div>
                    <strong className="small rr">Respiratory rate (/min)</strong>
                    <TrendChart times={times} min={0} max={40} low={p.thresholds.resp_rate.low} high={p.thresholds.resp_rate.high} series={[{ key: 'rr', label: 'RR', color: '#8a5a00', values: items.map((v) => v.resp_rate) }]} />
                  </div>
                  <div>
                    <strong className="small bp">Blood pressure (mmHg)</strong>
                    <TrendChart
                      times={times}
                      min={40}
                      max={200}
                      series={[
                        { key: 'sys', label: 'SYS', color: '#6d28d9', values: items.map((v) => v.systolic) },
                        { key: 'dia', label: 'DIA', color: '#a78bfa', values: items.map((v) => v.diastolic) },
                      ]}
                    />
                  </div>
                </>
              )}
            </div>
          </div>
          <Notes patientId={p.id} />
        </div>

        <div className="stack">
          <div className="card">
            <div className="card-head">
              <h2>Alarms</h2>
              <Link to={`/alarms`} className="small">
                All alarms
              </Link>
            </div>
            <div className="card-body">
              {activeAlarms.length === 0 && <EmptyState title="No active alarms" />}
              <div className="timeline">
                {activeAlarms.map((a) => (
                  <AlarmLine key={a.id} alarm={a} canAck={can(a.category === 'technical' ? 'alarms:ack_technical' : 'alarms:ack_clinical')} />
                ))}
              </div>
              {recentAlarms.length > 0 && (
                <details style={{ marginTop: 10 }}>
                  <summary className="small">Recent resolved alarms ({recentAlarms.length})</summary>
                  <div className="timeline">
                    {recentAlarms.slice(0, 10).map((a) => (
                      <AlarmLine key={a.id} alarm={a} canAck={false} />
                    ))}
                  </div>
                </details>
              )}
            </div>
          </div>
          <div className="card">
            <div className="card-head">
              <h2>Clinical summary</h2>
            </div>
            <div className="card-body stack small">
              <div>
                <span className="muted">Diagnosis</span>
                <div style={{ fontWeight: 600 }}>{p.diagnosis}</div>
              </div>
              <div className="grid grid-2">
                <div>
                  <span className="muted">Attending</span>
                  <div>Dr. {p.attending_physician}</div>
                </div>
                <div>
                  <span className="muted">Acuity</span>
                  <div style={{ textTransform: 'capitalize' }}>{p.acuity}</div>
                </div>
                <div>
                  <span className="muted">Allergies</span>
                  <div>{p.allergies}</div>
                </div>
                <div>
                  <span className="muted">Admitted</span>
                  <div>{fmtDateTime(p.admitted_at)}</div>
                </div>
              </div>
            </div>
          </div>
          <div className="card">
            <div className="card-head">
              <h2>Alarm limits</h2>
              {can('thresholds:edit_patient') && !editingLimits && (
                <button className="btn btn-sm" onClick={() => setEditingLimits(true)}>
                  <Pencil size={14} /> Edit
                </button>
              )}
            </div>
            {editingLimits ? (
              <div className="card-body">
                <ThresholdForm initial={p.thresholds} allowReset busy={limits.isPending} onCancel={() => setEditingLimits(false)} onSubmit={(items, reset) => limits.mutate({ items, reset })} />
              </div>
            ) : (
              <ThresholdTable thresholds={p.thresholds} />
            )}
          </div>
        </div>
      </div>
      {editing && <EditPatient patient={p} onClose={() => setEditing(false)} />}
    </>
  )
}
