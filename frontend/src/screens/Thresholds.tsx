import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router'
import { ThresholdForm, ThresholdTable } from '../components/ThresholdEditor'
import { EmptyState, ErrorState, Skeleton } from '../components/ui'
import { useToast } from '../hooks/useToast'
import { PARAM_LABELS } from '../lib/format'
import { errorMessage } from '../services/api'
import { Api } from '../services/endpoints'

export default function Thresholds() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [editing, setEditing] = useState(false)
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ['thresholds'], queryFn: Api.thresholdDefaults })
  const save = useMutation({
    mutationFn: Api.setThresholdDefaults,
    onSuccess: () => {
      toast('Ward default alarm limits saved. They apply from the next reading.', 'success')
      setEditing(false)
      void queryClient.invalidateQueries({ queryKey: ['thresholds'] })
    },
    onError: (err) => toast(errorMessage(err), 'error'),
  })

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Alarm limits</h1>
          <p>Ward defaults apply to every patient unless a physician sets patient-specific limits.</p>
        </div>
      </div>
      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      <div className="split">
        <div className="card">
          <div className="card-head">
            <h2>Ward 4B defaults</h2>
            {data?.can_edit_defaults && !editing && (
              <button className="btn btn-sm" onClick={() => setEditing(true)}>
                <Pencil size={14} /> Edit defaults
              </button>
            )}
          </div>
          {isLoading && (
            <div className="card-body">
              <Skeleton height={200} />
            </div>
          )}
          {data &&
            (editing ? (
              <div className="card-body">
                <ThresholdForm initial={data.defaults} allowReset={false} busy={save.isPending} onCancel={() => setEditing(false)} onSubmit={(items) => save.mutate(items)} />
              </div>
            ) : (
              <ThresholdTable thresholds={data.defaults} />
            ))}
        </div>
        <div className="card">
          <div className="card-head">
            <h2>Patient-specific limits</h2>
          </div>
          {data && data.overrides.length === 0 && <EmptyState title="No patient-specific limits" />}
          {data && data.overrides.length > 0 && (
            <table className="table">
              <thead>
                <tr>
                  <th>Patient</th>
                  <th>Parameter</th>
                  <th className="num">Low</th>
                  <th className="num">High</th>
                </tr>
              </thead>
              <tbody>
                {data.overrides.map((o) => (
                  <tr key={`${o.id}-${o.parameter}`}>
                    <td>
                      <Link to={`/patients/${o.id}`}>
                        {o.bed_id} · {o.first_name} {o.last_name}
                      </Link>
                    </td>
                    <td>{PARAM_LABELS[o.parameter].label}</td>
                    <td className="num">{o.enabled ? (o.low ?? '—') : 'off'}</td>
                    <td className="num">{o.enabled ? (o.high ?? '—') : 'off'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {data?.can_edit_patient && <p className="card-body muted small">Open a patient to change their limits.</p>}
        </div>
      </div>
    </>
  )
}
