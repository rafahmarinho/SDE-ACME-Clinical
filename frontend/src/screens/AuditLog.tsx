import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ShieldCheck, ShieldX } from 'lucide-react'
import { useState } from 'react'
import { EmptyState, Pagination, Skeleton } from '../components/ui'
import { useToast } from '../hooks/useToast'
import { fmtDateTime, relative } from '../lib/format'
import { errorMessage } from '../services/api'
import { Api } from '../services/endpoints'
import { MfaNotice } from './Team'

export default function AuditLog() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [q, setQ] = useState('')
  const [outcome, setOutcome] = useState('all')
  const [page, setPage] = useState(1)
  const params = { q, outcome, page, page_size: 50 }
  const log = useQuery({ queryKey: ['audit', params], queryFn: () => Api.audit(params), placeholderData: keepPreviousData, retry: false })
  const emergency = useQuery({ queryKey: ['emergency-log'], queryFn: Api.emergencyLog, enabled: log.isSuccess })
  const verify = useMutation({ mutationFn: Api.verifyAudit, onError: (err) => toast(errorMessage(err), 'error') })
  const review = useMutation({
    mutationFn: Api.reviewEmergency,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['emergency-log'] }),
    onError: (err) => toast(errorMessage(err), 'error'),
  })

  if (log.error) return <MfaNotice error={log.error} />

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Audit log</h1>
          <p>Every security-relevant action, chained with HMAC-SHA256 so that any change or deletion is detectable.</p>
        </div>
        <div className="row">
          {verify.data &&
            (verify.data.valid ? (
              <span className="badge badge-ok">
                <ShieldCheck size={14} /> Integrity verified · {verify.data.checked} records
              </span>
            ) : (
              <span className="badge badge-critical">
                <ShieldX size={14} /> Tampering detected at record #{verify.data.broken_at}
              </span>
            ))}
          <button className="btn" onClick={() => verify.mutate()} disabled={verify.isPending}>
            {verify.isPending ? 'Verifying…' : 'Verify integrity'}
          </button>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Emergency (break-glass) access</h2>
        </div>
        {emergency.data?.items.length === 0 && <EmptyState title="No emergency access has been used" />}
        {emergency.data && emergency.data.items.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Granted</th>
                <th>User</th>
                <th>Patient</th>
                <th>Reason</th>
                <th>Review</th>
              </tr>
            </thead>
            <tbody>
              {emergency.data.items.map((e) => (
                <tr key={e.id}>
                  <td className="small">
                    {fmtDateTime(e.granted_at)}
                    <div className="muted">until {fmtDateTime(e.expires_at)}</div>
                  </td>
                  <td>
                    {e.user_name}
                    <div className="muted small">{e.role}</div>
                  </td>
                  <td>
                    {e.bed_id} · {e.patient_name}
                  </td>
                  <td className="small">{e.reason}</td>
                  <td>
                    {e.reviewed_at ? (
                      <span className="badge badge-ok">Reviewed {relative(e.reviewed_at)}</span>
                    ) : (
                      <button className="btn btn-sm" onClick={() => review.mutate(e.id)}>
                        Mark reviewed
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="card">
        <div className="card-body toolbar">
          <input className="input" placeholder="Filter by action, e-mail or record" value={q} onChange={(e) => (setQ(e.target.value), setPage(1))} maxLength={100} aria-label="Filter audit log" style={{ minWidth: 280 }} />
          <select className="select" value={outcome} onChange={(e) => (setOutcome(e.target.value), setPage(1))} aria-label="Outcome">
            <option value="all">All outcomes</option>
            <option value="success">Success</option>
            <option value="failure">Failure</option>
            <option value="denied">Denied</option>
          </select>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>#</th>
                <th>Time</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Record</th>
                <th>Outcome</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {log.isLoading && (
                <tr>
                  <td colSpan={7}>
                    <Skeleton height={200} />
                  </td>
                </tr>
              )}
              {log.data?.items.map((a) => (
                <tr key={a.id}>
                  <td className="mono">{a.id}</td>
                  <td className="small num">{fmtDateTime(a.created_at)}</td>
                  <td className="small">
                    {a.actor_email ?? 'system'}
                    <div className="muted">
                      {a.actor_role ?? ''} {a.ip ? `· ${a.ip}` : ''}
                    </div>
                  </td>
                  <td className="mono">{a.action}</td>
                  <td className="small">{a.entity_type ? `${a.entity_type} ${a.entity_id ?? ''}` : '—'}</td>
                  <td>
                    <span className={`badge ${a.outcome === 'success' ? 'badge-ok' : a.outcome === 'denied' ? 'badge-critical' : 'badge-warning'}`}>{a.outcome}</span>
                  </td>
                  <td className="mono small" style={{ maxWidth: 320, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {Object.keys(a.details).length ? JSON.stringify(a.details) : ''}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {log.data && <Pagination page={log.data.page} pageSize={log.data.page_size} total={log.data.total} onPage={setPage} />}
      </div>
    </>
  )
}
