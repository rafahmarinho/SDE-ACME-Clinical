import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ShieldAlert, UserPlus } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { Link } from 'react-router'
import { Avatar, ConfirmDialog, EmptyState, ErrorState, Field, Modal, Skeleton } from '../components/ui'
import { useToast } from '../hooks/useToast'
import { fmtDateTime, relative, ROLE_LABELS } from '../lib/format'
import { ApiError, errorMessage } from '../services/api'
import { Api } from '../services/endpoints'
import type { Role, TeamMember } from '../services/types'

function MfaNotice({ error }: { error: unknown }) {
  if (error instanceof ApiError && error.code === 'mfa_required_admin') {
    return (
      <div className="alert alert-warning" role="alert">
        <ShieldAlert size={18} />
        <div>
          {error.message} <Link to="/settings?tab=security">Set up two-factor authentication</Link>, then sign out and back in.
        </div>
      </div>
    )
  }
  return <ErrorState error={error} />
}

export { MfaNotice }

function InviteDialog({ onClose }: { onClose: () => void }) {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [form, setForm] = useState({ email: '', full_name: '', role: 'nurse' as Role, job_title: '' })
  const [error, setError] = useState<string | null>(null)
  const invite = useMutation({
    mutationFn: () => Api.invite(form),
    onSuccess: () => {
      toast(`Invitation sent to ${form.email}.`, 'success')
      void queryClient.invalidateQueries({ queryKey: ['team'] })
      onClose()
    },
    onError: (err) => setError(errorMessage(err)),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    setError(null)
    invite.mutate()
  }
  return (
    <Modal title="Invite a team member" onClose={onClose}>
      <form className="stack" onSubmit={submit}>
        {error && <div className="alert alert-error">{error}</div>}
        <Field label="Full name" htmlFor="inv-name">
          <input id="inv-name" className="input" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required maxLength={120} autoComplete="off" />
        </Field>
        <Field label="Work e-mail" htmlFor="inv-email" hint="They receive a single-use link to set their password.">
          <input id="inv-email" type="email" className="input" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} required maxLength={254} autoComplete="off" />
        </Field>
        <div className="grid grid-2">
          <Field label="Role" htmlFor="inv-role">
            <select id="inv-role" className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
              {(Object.keys(ROLE_LABELS) as Role[]).map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABELS[r]}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Job title (optional)" htmlFor="inv-title">
            <input id="inv-title" className="input" value={form.job_title} onChange={(e) => setForm({ ...form, job_title: e.target.value })} maxLength={80} autoComplete="off" />
          </Field>
        </div>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={invite.isPending}>
            {invite.isPending ? 'Sending…' : 'Send invitation'}
          </button>
        </div>
      </form>
    </Modal>
  )
}

export default function Team() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const [q, setQ] = useState('')
  const [role, setRole] = useState('all')
  const [status, setStatus] = useState('all')
  const [inviting, setInviting] = useState(false)
  const [confirm, setConfirm] = useState<{ member: TeamMember; action: 'deactivate' | 'anonymize' } | null>(null)
  const params = { q, role, status }
  const team = useQuery({ queryKey: ['team', params], queryFn: () => Api.team(params), retry: false })
  const requests = useQuery({ queryKey: ['privacy-requests'], queryFn: Api.privacyRequests, retry: false, enabled: team.isSuccess })
  const refresh = () => ['team', 'privacy-requests'].forEach((k) => void queryClient.invalidateQueries({ queryKey: [k] }))
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { role?: Role; active?: boolean } }) => Api.updateMember(id, body),
    onSuccess: () => (toast('Team member updated. Their current sessions were signed out where needed.', 'success'), setConfirm(null), refresh()),
    onError: (err) => (setConfirm(null), toast(errorMessage(err), 'error')),
  })
  const anonymize = useMutation({
    mutationFn: (id: string) => Api.anonymize(id),
    onSuccess: () => (toast('Personal data removed. The account is closed.', 'success'), setConfirm(null), refresh()),
    onError: (err) => (setConfirm(null), toast(errorMessage(err), 'error')),
  })
  const decide = useMutation({
    mutationFn: ({ id, status }: { id: string; status: 'completed' | 'rejected' }) => Api.decidePrivacyRequest(id, status),
    onSuccess: refresh,
    onError: (err) => toast(errorMessage(err), 'error'),
  })

  if (team.error) return <MfaNotice error={team.error} />

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Team</h1>
          <p>Staff accounts are created by invitation only. Role changes take effect at the member’s next sign-in.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setInviting(true)}>
          <UserPlus size={16} /> Invite member
        </button>
      </div>
      <div className="card">
        <div className="card-body toolbar">
          <input className="input" placeholder="Search by name or e-mail" value={q} onChange={(e) => setQ(e.target.value)} maxLength={100} aria-label="Search team" style={{ minWidth: 260 }} />
          <select className="select" value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role">
            <option value="all">All roles</option>
            {(Object.keys(ROLE_LABELS) as Role[]).map((r) => (
              <option key={r} value={r}>
                {ROLE_LABELS[r]}
              </option>
            ))}
          </select>
          <select className="select" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
            <option value="all">Active and inactive</option>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
          </select>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Member</th>
                <th>Role</th>
                <th>Status</th>
                <th>Last sign-in</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {team.isLoading && (
                <tr>
                  <td colSpan={5}>
                    <Skeleton height={120} />
                  </td>
                </tr>
              )}
              {team.data?.items.map((m) => (
                <tr key={m.id}>
                  <td>
                    <div className="row">
                      <Avatar name={m.full_name} url={m.avatar_url} />
                      <div>
                        <strong>{m.full_name}</strong> {m.is_self && <span className="badge badge-navy">You</span>}
                        <div className="muted small">
                          {m.email}
                          {m.job_title ? ` · ${m.job_title}` : ''}
                        </div>
                      </div>
                    </div>
                  </td>
                  <td>
                    <select
                      className="select"
                      value={m.role}
                      disabled={m.is_self || !!m.anonymized_at || update.isPending}
                      onChange={(e) => update.mutate({ id: m.id, body: { role: e.target.value as Role } })}
                      aria-label={`Role of ${m.full_name}`}
                    >
                      {(Object.keys(ROLE_LABELS) as Role[]).map((r) => (
                        <option key={r} value={r}>
                          {ROLE_LABELS[r]}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    {m.anonymized_at ? (
                      <span className="badge badge-muted">Anonymized</span>
                    ) : m.active ? (
                      <span className="badge badge-ok">Active · {m.active_sessions} session(s)</span>
                    ) : (
                      <span className="badge badge-muted">Inactive</span>
                    )}
                  </td>
                  <td className="small">{m.last_sign_in_at ? relative(m.last_sign_in_at) : 'Never'}</td>
                  <td>
                    {!m.is_self && !m.anonymized_at && (
                      <div className="row" style={{ justifyContent: 'flex-end' }}>
                        {m.active ? (
                          <button className="btn btn-sm" onClick={() => setConfirm({ member: m, action: 'deactivate' })}>
                            Deactivate
                          </button>
                        ) : (
                          <button className="btn btn-sm" onClick={() => update.mutate({ id: m.id, body: { active: true } })}>
                            Reactivate
                          </button>
                        )}
                        <button className="btn btn-sm btn-ghost" onClick={() => setConfirm({ member: m, action: 'anonymize' })}>
                          Remove personal data
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {team.data?.items.length === 0 && <EmptyState title="No team members match" />}
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <h2>Privacy requests</h2>
        </div>
        {requests.data?.items.length === 0 && <EmptyState title="No privacy requests" />}
        {requests.data && requests.data.items.length > 0 && (
          <table className="table">
            <thead>
              <tr>
                <th>Requested</th>
                <th>Member</th>
                <th>Request</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {requests.data.items.map((r) => (
                <tr key={r.id}>
                  <td className="small">{fmtDateTime(r.created_at)}</td>
                  <td>
                    {r.full_name}
                    <div className="muted small">{r.email}</div>
                  </td>
                  <td>
                    {r.kind === 'deletion' ? 'Delete my personal data' : 'Consent withdrawn'}
                    {r.details && <div className="muted small">{r.details}</div>}
                  </td>
                  <td>
                    <span className={`badge ${r.status === 'pending' ? 'badge-warning' : 'badge-muted'}`}>{r.status}</span>
                  </td>
                  <td>
                    {r.status === 'pending' && (
                      <div className="row">
                        {r.kind === 'deletion' && (
                          <button className="btn btn-sm btn-danger" onClick={() => anonymize.mutate(r.user_id)}>
                            Remove data
                          </button>
                        )}
                        <button className="btn btn-sm" onClick={() => decide.mutate({ id: r.id, status: r.kind === 'deletion' ? 'rejected' : 'completed' })}>
                          {r.kind === 'deletion' ? 'Reject' : 'Mark handled'}
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {inviting && <InviteDialog onClose={() => setInviting(false)} />}
      {confirm?.action === 'deactivate' && (
        <ConfirmDialog
          title={`Deactivate ${confirm.member.full_name}?`}
          body="They are signed out everywhere immediately and cannot sign in until reactivated."
          confirmLabel="Deactivate"
          danger
          busy={update.isPending}
          onConfirm={() => update.mutate({ id: confirm.member.id, body: { active: false } })}
          onClose={() => setConfirm(null)}
        />
      )}
      {confirm?.action === 'anonymize' && (
        <ConfirmDialog
          title={`Remove personal data for ${confirm.member.full_name}?`}
          body="Name, e-mail, phone, photo and preferences are erased and the account is closed permanently. Clinical records keep an anonymous author for patient safety."
          confirmLabel="Remove personal data"
          danger
          requireText="REMOVE"
          busy={anonymize.isPending}
          onConfirm={() => anonymize.mutate(confirm.member.id)}
          onClose={() => setConfirm(null)}
        />
      )}
    </>
  )
}
