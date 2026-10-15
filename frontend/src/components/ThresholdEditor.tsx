import { useState } from 'react'
import { PARAM_LABELS } from '../lib/format'
import type { ThresholdItem } from '../services/endpoints'
import type { Threshold, VitalKey } from '../services/types'

const KEYS: VitalKey[] = ['heart_rate', 'spo2', 'resp_rate', 'systolic', 'diastolic']

export function ThresholdTable({ thresholds }: { thresholds: Record<VitalKey, Threshold> }) {
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Parameter</th>
          <th className="num">Low</th>
          <th className="num">High</th>
          <th>Source</th>
        </tr>
      </thead>
      <tbody>
        {KEYS.map((k) => {
          const t = thresholds[k]
          return (
            <tr key={k}>
              <td>{PARAM_LABELS[k].label}</td>
              <td className="num">{t?.enabled ? (t.low ?? '—') : 'off'}</td>
              <td className="num">{t?.enabled ? (t.high ?? '—') : 'off'}</td>
              <td>{t?.source === 'patient' ? <span className="badge badge-navy">Patient order</span> : <span className="badge badge-muted">Ward default</span>}</td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}

/** Editable rows; returns the items and the parameters to reset to the ward default. */
export function ThresholdForm({
  initial,
  allowReset,
  onSubmit,
  busy,
  onCancel,
}: {
  initial: Record<VitalKey, Threshold>
  allowReset: boolean
  onSubmit: (items: ThresholdItem[], reset: VitalKey[]) => void
  busy: boolean
  onCancel: () => void
}) {
  const [rows, setRows] = useState(() =>
    KEYS.map((k) => ({
      parameter: k,
      low: initial[k]?.low?.toString() ?? '',
      high: initial[k]?.high?.toString() ?? '',
      enabled: initial[k]?.enabled ?? true,
      reset: false,
      source: initial[k]?.source,
    })),
  )
  const update = (i: number, patch: Partial<(typeof rows)[number]>) => setRows((r) => r.map((row, j) => (j === i ? { ...row, ...patch } : row)))
  const submit = () => {
    const items: ThresholdItem[] = rows
      .filter((r) => !r.reset)
      .map((r) => ({
        parameter: r.parameter,
        low: r.low === '' ? null : Number(r.low),
        high: r.high === '' ? null : Number(r.high),
        enabled: r.enabled,
      }))
    const reset = rows.filter((r) => r.reset).map((r) => r.parameter)
    onSubmit(items.length ? items : [], reset)
  }
  return (
    <div className="stack">
      <table className="table">
        <thead>
          <tr>
            <th>Parameter</th>
            <th>Low</th>
            <th>High</th>
            <th>Alarm on</th>
            {allowReset && <th>Use default</th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.parameter}>
              <td>
                {PARAM_LABELS[r.parameter].label} <span className="muted small">({PARAM_LABELS[r.parameter].unit})</span>
              </td>
              <td>
                <input className="input num" type="number" inputMode="decimal" value={r.low} disabled={r.reset} onChange={(e) => update(i, { low: e.target.value })} style={{ width: 90 }} aria-label={`${PARAM_LABELS[r.parameter].label} low`} />
              </td>
              <td>
                <input className="input num" type="number" inputMode="decimal" value={r.high} disabled={r.reset} onChange={(e) => update(i, { high: e.target.value })} style={{ width: 90 }} aria-label={`${PARAM_LABELS[r.parameter].label} high`} />
              </td>
              <td>
                <input type="checkbox" checked={r.enabled} disabled={r.reset} onChange={(e) => update(i, { enabled: e.target.checked })} aria-label="Alarm enabled" />
              </td>
              {allowReset && (
                <td>
                  <input type="checkbox" checked={r.reset} onChange={(e) => update(i, { reset: e.target.checked })} aria-label="Reset to ward default" />
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="row" style={{ justifyContent: 'flex-end' }}>
        <button className="btn" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button className="btn btn-primary" onClick={submit} disabled={busy}>
          {busy ? 'Saving…' : 'Save alarm limits'}
        </button>
      </div>
    </div>
  )
}
