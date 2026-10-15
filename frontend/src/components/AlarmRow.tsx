import { useMutation, useQueryClient } from '@tanstack/react-query'
import { CheckCheck } from 'lucide-react'
import { useState } from 'react'
import { useToast } from '../hooks/useToast'
import { ALARM_LABELS, fmtTime, relative } from '../lib/format'
import { errorMessage } from '../services/api'
import { Api } from '../services/endpoints'
import type { Alarm } from '../services/types'
import { Field, Modal, SeverityBadge } from './ui'

export function AckButton({ alarm }: { alarm: Alarm }) {
  const queryClient = useQueryClient()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')
  const mutation = useMutation({
    mutationFn: () => Api.acknowledge(alarm.id, note.trim()),
    onSuccess: (result) => {
      toast(result.message, 'success')
      setOpen(false)
      setNote('')
      ;['alarms', 'overview', 'patient', 'device'].forEach((key) => void queryClient.invalidateQueries({ queryKey: [key] }))
    },
    onError: (err) => toast(errorMessage(err), 'error'),
  })
  return (
    <>
      <button className="btn btn-sm btn-primary" onClick={() => setOpen(true)}>
        <CheckCheck size={14} /> Acknowledge
      </button>
      {open && (
        <Modal
          title="Acknowledge alarm"
          onClose={() => setOpen(false)}
          footer={
            <>
              <button className="btn" onClick={() => setOpen(false)}>
                Cancel
              </button>
              <button className="btn btn-primary" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
                {mutation.isPending ? 'Saving…' : 'Acknowledge'}
              </button>
            </>
          }
        >
          <div className="row">
            <SeverityBadge severity={alarm.severity} />
            <strong>{ALARM_LABELS[alarm.type] ?? alarm.type}</strong>
            {alarm.bed_id && <span className="muted">{alarm.bed_id}</span>}
          </div>
          <p>{alarm.message}</p>
          {alarm.state === 'active' && (
            <div className="alert alert-warning">
              Acknowledging records that you are responding. The alarm stays active until the monitor reports that the condition has cleared.
            </div>
          )}
          <Field label="Note (optional)" htmlFor="ack-note" hint="For example: oxygen increased, repositioned probe.">
            <input id="ack-note" className="input" value={note} onChange={(e) => setNote(e.target.value)} maxLength={200} autoComplete="off" />
          </Field>
        </Modal>
      )}
    </>
  )
}

export function AlarmStateBadge({ alarm }: { alarm: Alarm }) {
  if (alarm.state === 'resolved') return <span className="badge badge-muted">Resolved {alarm.resolved_at ? fmtTime(alarm.resolved_at) : ''}</span>
  if (alarm.acknowledged_at) return <span className="badge badge-warning">Acknowledged · condition still active</span>
  return (
    <span className="badge badge-critical">
      <span className="dot pulse" /> Active
    </span>
  )
}

export function AlarmLine({ alarm, canAck }: { alarm: Alarm; canAck: boolean }) {
  return (
    <div className="timeline-item">
      <div className="small muted num">
        {fmtTime(alarm.raised_at)}
        <div>{relative(alarm.raised_at)}</div>
      </div>
      <div className="stack" style={{ gap: 6 }}>
        <div className="row">
          <SeverityBadge severity={alarm.severity} />
          <strong>{ALARM_LABELS[alarm.type] ?? alarm.type}</strong>
          <AlarmStateBadge alarm={alarm} />
        </div>
        <span className="small">{alarm.message}</span>
        {alarm.acknowledged_at && (
          <span className="small muted">
            Acknowledged by {alarm.acknowledged_by_name} at {fmtTime(alarm.acknowledged_at)}
            {alarm.ack_note ? ` — “${alarm.ack_note}”` : ''}
          </span>
        )}
        {canAck && !alarm.acknowledged_at && (
          <div>
            <AckButton alarm={alarm} />
          </div>
        )}
      </div>
    </div>
  )
}
