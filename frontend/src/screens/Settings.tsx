import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, KeyRound, LogOut, ShieldCheck } from 'lucide-react'
import { type FormEvent, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { ConfirmDialog, ErrorState, Field, PasswordInput, Spinner } from '../components/ui'
import { useAuth } from '../hooks/useAuth'
import { useToast } from '../hooks/useToast'
import { fmtDateTime, relative } from '../lib/format'
import { passwordIssues } from '../lib/password'
import { download, errorMessage } from '../services/api'
import { syncMfa } from '../services/auth'
import { Api } from '../services/endpoints'
import { supabase } from '../services/supabase'
import type { Preferences } from '../services/types'

function PreferencesTab() {
  const { me, refresh } = useAuth()
  const toast = useToast()
  const [prefs, setPrefs] = useState<Preferences>(me!.preferences)
  const save = useMutation({
    mutationFn: () => Api.updatePreferences(prefs),
    onSuccess: async () => {
      await refresh()
      toast('Preferences saved.', 'success')
    },
    onError: (err) => toast(errorMessage(err), 'error'),
  })
  return (
    <div className="card card-pad stack" style={{ maxWidth: 680 }}>
      <Field label="Start page after sign-in" htmlFor="landing">
        <select id="landing" className="select" value={prefs.landing_page} onChange={(e) => setPrefs({ ...prefs, landing_page: e.target.value })}>
          <option value="/">Ward overview</option>
          {me!.permissions.includes('patients:view') && <option value="/patients">Patients</option>}
          {me!.permissions.includes('vitals:view') && <option value="/monitoring">Live monitoring</option>}
          <option value="/alarms">Alarms</option>
          <option value="/devices">Devices</option>
          <option value="/reports">Reports</option>
        </select>
      </Field>
      <Field label="Ward overview layout" htmlFor="ward-view">
        <select id="ward-view" className="select" value={prefs.ward_view} onChange={(e) => setPrefs({ ...prefs, ward_view: e.target.value as Preferences['ward_view'] })}>
          <option value="grid">Bed cards</option>
          <option value="3d">3D ward</option>
        </select>
      </Field>
      <Field label="Density" htmlFor="density">
        <select id="density" className="select" value={prefs.density} onChange={(e) => setPrefs({ ...prefs, density: e.target.value as Preferences['density'] })}>
          <option value="comfortable">Comfortable</option>
          <option value="compact">Compact</option>
        </select>
      </Field>
      <label className="checkbox">
        <input type="checkbox" checked={prefs.critical_banner} onChange={(e) => setPrefs({ ...prefs, critical_banner: e.target.checked })} />
        Show a banner for unacknowledged critical alarms
      </label>
      <label className="checkbox">
        <input type="checkbox" checked={prefs.alarm_sound} onChange={(e) => setPrefs({ ...prefs, alarm_sound: e.target.checked })} />
        Play a sound when a new critical alarm appears
      </label>
      <div>
        <button className="btn btn-primary" onClick={() => save.mutate()} disabled={save.isPending}>
          Save preferences
        </button>
      </div>
    </div>
  )
}

function PasswordCard() {
  const toast = useToast()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const policy = useQuery({ queryKey: ['policy'], queryFn: Api.passwordPolicy, staleTime: Infinity })
  const issues = useMemo(() => passwordIssues(next, policy.data?.password.min_length ?? 12), [next, policy.data])
  const change = useMutation({
    mutationFn: () => Api.changePassword({ current_password: current, new_password: next }),
    onSuccess: (r) => {
      toast(r.message, 'success')
      setCurrent('')
      setNext('')
      setConfirm('')
    },
    onError: (err) => toast(errorMessage(err), 'error'),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (next !== confirm) {
      toast('The new passwords do not match.', 'error')
      return
    }
    change.mutate()
  }
  return (
    <form className="card card-pad stack" onSubmit={submit}>
      <h2 className="row">
        <KeyRound size={18} /> Change password
      </h2>
      <Field label="Current password" htmlFor="cur">
        <PasswordInput id="cur" value={current} onChange={setCurrent} autoComplete="current-password" />
      </Field>
      <Field label="New password" htmlFor="new" hint={next ? (issues.length ? `Needs ${issues.join(', ')}.` : 'Strong password.') : `At least ${policy.data?.password.min_length ?? 12} characters with upper and lower case, a number and a symbol.`}>
        <PasswordInput id="new" value={next} onChange={setNext} autoComplete="new-password" />
      </Field>
      <Field label="Confirm new password" htmlFor="confirm">
        <PasswordInput id="confirm" value={confirm} onChange={setConfirm} autoComplete="new-password" />
      </Field>
      <div>
        <button className="btn btn-primary" disabled={change.isPending || !current || issues.length > 0 || !confirm}>
          {change.isPending ? 'Updating…' : 'Update password'}
        </button>
      </div>
    </form>
  )
}

function MfaCard() {
  const { me, refresh } = useAuth()
  const toast = useToast()
  const [enrolling, setEnrolling] = useState<{ id: string; qr: string; secret: string } | null>(null)
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const factors = useQuery({ queryKey: ['mfa-factors'], queryFn: async () => (await supabase.auth.mfa.listFactors()).data?.totp ?? [] })
  const verified = (factors.data ?? []).filter((f) => f.status === 'verified')

  const start = async () => {
    setBusy(true)
    try {
      // clean up abandoned enrolments first
      for (const f of (factors.data ?? []).filter((x) => x.status !== 'verified')) await supabase.auth.mfa.unenroll({ factorId: f.id })
      const { data, error } = await supabase.auth.mfa.enroll({ factorType: 'totp', friendlyName: `ACME Clinical ${Date.now()}` })
      if (error) throw error
      setEnrolling({ id: data.id, qr: data.totp.qr_code, secret: data.totp.secret })
    } catch (err) {
      toast(err instanceof Error ? err.message : errorMessage(err), 'error')
    } finally {
      setBusy(false)
    }
  }
  const verify = async (e: FormEvent) => {
    e.preventDefault()
    if (!enrolling) return
    setBusy(true)
    try {
      const { error } = await supabase.auth.mfa.challengeAndVerify({ factorId: enrolling.id, code: code.trim() })
      if (error) throw new Error('That code is not valid. Try the next one from your app.')
      await syncMfa()
      setEnrolling(null)
      setCode('')
      await factors.refetch()
      await refresh()
      toast('Two-factor authentication is on.', 'success')
    } catch (err) {
      toast(err instanceof Error ? err.message : errorMessage(err), 'error')
    } finally {
      setBusy(false)
    }
  }
  const remove = async () => {
    setBusy(true)
    try {
      for (const f of verified) {
        const { error } = await supabase.auth.mfa.unenroll({ factorId: f.id })
        if (error) throw error
      }
      await syncMfa()
      await factors.refetch()
      await refresh()
      toast('Two-factor authentication removed.', 'success')
    } catch (err) {
      toast(err instanceof Error ? err.message : errorMessage(err), 'error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="card card-pad stack">
      <h2 className="row">
        <ShieldCheck size={18} /> Two-factor authentication
      </h2>
      <p className="muted small">
        Use an authenticator app (time-based codes). {me?.role === 'admin' && 'Administrators need it for team management, the audit log and data reset.'}
      </p>
      {factors.isLoading && <Spinner />}
      {verified.length > 0 && !enrolling && (
        <div className="row">
          <span className="badge badge-ok">On · session level {me?.session.aal.toUpperCase()}</span>
          <button className="btn btn-sm" onClick={remove} disabled={busy}>
            Turn off
          </button>
        </div>
      )}
      {verified.length === 0 && !enrolling && (
        <div>
          <button className="btn btn-primary" onClick={start} disabled={busy}>
            Set up authenticator app
          </button>
        </div>
      )}
      {enrolling && (
        <form className="stack" onSubmit={verify}>
          <div className="row" style={{ alignItems: 'flex-start' }}>
            <img src={enrolling.qr} alt="QR code for your authenticator app" width={168} height={168} style={{ border: '1px solid var(--border)', borderRadius: 8 }} />
            <div className="small stack" style={{ gap: 6, flex: 1 }}>
              <span>Scan the QR code, or enter this key manually:</span>
              <code className="mono" style={{ wordBreak: 'break-all' }}>
                {enrolling.secret}
              </code>
            </div>
          </div>
          <Field label="6-digit code" htmlFor="totp">
            <input id="totp" className="input num" value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} inputMode="numeric" autoComplete="one-time-code" maxLength={6} required />
          </Field>
          <div className="row">
            <button className="btn btn-primary" disabled={busy || code.length !== 6}>
              Verify and turn on
            </button>
            <button type="button" className="btn" onClick={() => setEnrolling(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  )
}

function SessionsCard() {
  const toast = useToast()
  const queryClient = useQueryClient()
  const sessions = useQuery({ queryKey: ['sessions'], queryFn: Api.sessions })
  const revoke = useMutation({
    mutationFn: Api.revokeOtherSessions,
    onSuccess: (r) => {
      toast(`${r.revoked} other session(s) signed out.`, 'success')
      void queryClient.invalidateQueries({ queryKey: ['sessions'] })
    },
    onError: (err) => toast(errorMessage(err), 'error'),
  })
  return (
    <div className="card">
      <div className="card-head">
        <h2>Active sessions</h2>
        <button className="btn btn-sm" onClick={() => revoke.mutate()} disabled={revoke.isPending}>
          <LogOut size={14} /> Sign out other sessions
        </button>
      </div>
      {sessions.error && <ErrorState error={sessions.error} />}
      <table className="table">
        <tbody>
          {sessions.data?.items.map((s) => (
            <tr key={s.session_id}>
              <td className="small">
                <strong>{s.user_agent?.slice(0, 60) || 'Unknown device'}</strong>
                <div className="muted">
                  {s.ip ?? 'unknown address'} · started {fmtDateTime(s.created_at)} · active {relative(s.last_seen_at)}
                </div>
              </td>
              <td>{s.current && <span className="badge badge-ok">This session</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PrivacyTab() {
  const { me, refresh, signOut } = useAuth()
  const toast = useToast()
  const [details, setDetails] = useState('')
  const [withdrawing, setWithdrawing] = useState(false)
  const pendingDeletion = me?.privacy_requests.some((r) => r.kind === 'deletion' && r.status === 'pending')
  const request = useMutation({
    mutationFn: () => Api.requestDeletion(details.trim()),
    onSuccess: async () => {
      await refresh()
      toast('Your request was sent to the administrators.', 'success')
    },
    onError: (err) => toast(errorMessage(err), 'error'),
  })
  const withdraw = useMutation({
    mutationFn: Api.withdrawConsent,
    onSuccess: () => void signOut('You withdrew your consent. An administrator will contact you about your account.'),
    onError: (err) => toast(errorMessage(err), 'error'),
  })
  return (
    <div className="grid grid-2">
      <div className="card card-pad stack">
        <h2>Your data</h2>
        <p className="small muted">
          Download a copy of the personal data ACME Clinical holds about you: profile, preferences, sessions and recent activity. Processing
          purpose: staff identification, patient-safety audit trail and access control.
        </p>
        <div>
          <button className="btn" onClick={() => download('/me/export', 'acme-clinical-my-data.json').catch((err) => toast(errorMessage(err), 'error'))}>
            <Download size={16} /> Download my data (JSON)
          </button>
        </div>
        <p className="small">
          Privacy notice accepted: {me?.consent.accepted_at ? `${fmtDateTime(me.consent.accepted_at)} (version ${me.consent.version})` : 'not accepted'}
        </p>
      </div>
      <div className="card card-pad stack">
        <h2>Delete or restrict</h2>
        <p className="small muted">Ask an administrator to remove your personal data. Clinical entries you made stay in patient records under an anonymous author.</p>
        {pendingDeletion ? (
          <span className="badge badge-warning">Deletion request pending</span>
        ) : (
          <>
            <Field label="Comment (optional)" htmlFor="del-details">
              <input id="del-details" className="input" value={details} onChange={(e) => setDetails(e.target.value)} maxLength={200} />
            </Field>
            <div>
              <button className="btn" onClick={() => request.mutate()} disabled={request.isPending}>
                Request deletion of my data
              </button>
            </div>
          </>
        )}
        <hr style={{ border: 'none', borderTop: '1px solid var(--border)', width: '100%' }} />
        <div>
          <button className="btn btn-danger" onClick={() => setWithdrawing(true)}>
            Withdraw consent
          </button>
        </div>
      </div>
      {withdrawing && (
        <ConfirmDialog
          title="Withdraw your consent?"
          body="You will be signed out and will need to accept the privacy notice again to use ACME Clinical. The privacy office is notified."
          confirmLabel="Withdraw and sign out"
          danger
          busy={withdraw.isPending}
          onConfirm={() => withdraw.mutate()}
          onClose={() => setWithdrawing(false)}
        />
      )}
    </div>
  )
}

function SystemTab() {
  const config = useQuery({ queryKey: ['security-settings'], queryFn: Api.securitySettings, retry: false })
  if (config.error) return <ErrorState error={config.error} />
  if (!config.data) return <Spinner />
  return (
    <div className="card">
      <div className="card-head">
        <h2>Effective security configuration</h2>
        <span className="muted small">Managed through the API environment variables</span>
      </div>
      <table className="table">
        <tbody>
          {Object.entries(config.data).map(([k, v]) => (
            <tr key={k}>
              <td style={{ width: 260, fontWeight: 600 }}>{k.replace(/_/g, ' ')}</td>
              <td className="mono">{typeof v === 'object' ? JSON.stringify(v) : String(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function Settings() {
  const { can } = useAuth()
  const [params, setParams] = useSearchParams()
  const tabs = [
    { id: 'preferences', label: 'Preferences' },
    { id: 'security', label: 'Security' },
    { id: 'privacy', label: 'Privacy' },
    ...(can('team:manage') ? [{ id: 'system', label: 'System' }] : []),
  ]
  const tab = tabs.some((t) => t.id === params.get('tab')) ? params.get('tab')! : 'preferences'
  useEffect(() => {
    document.title = 'Settings · ACME Clinical'
  }, [])
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p>Personal preferences, sign-in security and privacy choices.</p>
        </div>
      </div>
      <div className="tabs" role="tablist">
        {tabs.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'active' : ''} onClick={() => setParams({ tab: t.id })}>
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'preferences' && <PreferencesTab />}
      {tab === 'security' && (
        <div className="stack">
          <div className="grid grid-2">
            <PasswordCard />
            <MfaCard />
          </div>
          <SessionsCard />
        </div>
      )}
      {tab === 'privacy' && <PrivacyTab />}
      {tab === 'system' && <SystemTab />}
    </>
  )
}
