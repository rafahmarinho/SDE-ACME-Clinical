import { type FormEvent, useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { Field, PasswordInput } from '../../components/ui'
import { passwordIssues } from '../../lib/password'
import { errorMessage } from '../../services/api'
import { completePasswordReset } from '../../services/auth'
import { AuthFrame } from './AuthFrame'

/** Handles both password-recovery and invitation links (single-use token in the URL fragment). */
export default function ResetPassword({ mode }: { mode: 'reset' | 'invite' }) {
  const navigate = useNavigate()
  const [token] = useState(() => {
    const params = new URLSearchParams(window.location.hash.slice(1))
    return { access: params.get('access_token'), error: params.get('error_description') }
  })
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(token.error)
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const issues = useMemo(() => passwordIssues(password), [password])

  // Remove the token from the address bar and browser history immediately.
  useEffect(() => {
    if (window.location.hash) window.history.replaceState(null, '', window.location.pathname)
  }, [])

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!token.access) return
    if (password !== confirm) {
      setError('The passwords do not match.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const result = await completePasswordReset(token.access, password)
      setDone(result.message)
      setPassword('')
      setConfirm('')
      window.setTimeout(() => navigate('/login', { replace: true }), 2500)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthFrame>
      <div className="stack" style={{ gap: 6 }}>
        <h1>{mode === 'invite' ? 'Welcome to ACME Clinical' : 'Choose a new password'}</h1>
        <p className="muted">{mode === 'invite' ? 'Set a password to activate your staff account.' : 'Your new password signs out all your other sessions.'}</p>
      </div>
      {!token.access && !done && (
        <div className="alert alert-error" role="alert">
          This link is invalid or has expired. <Link to="/forgot-password">Request a new link</Link>.
        </div>
      )}
      {done && (
        <div className="alert alert-success" role="status">
          {done}
        </div>
      )}
      {error && token.access && !done && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}
      {token.access && !done && (
        <form className="stack" onSubmit={submit}>
          <Field label="New password" htmlFor="new-password" hint={issues.length ? `Needs ${issues.join(', ')}.` : 'Strong password.'}>
            <PasswordInput id="new-password" value={password} onChange={setPassword} autoComplete="new-password" />
          </Field>
          <Field label="Confirm password" htmlFor="confirm-password">
            <PasswordInput id="confirm-password" value={confirm} onChange={setConfirm} autoComplete="new-password" />
          </Field>
          <button className="btn btn-primary btn-lg btn-block" disabled={busy || issues.length > 0 || !confirm}>
            {busy ? 'Saving…' : mode === 'invite' ? 'Activate account' : 'Update password'}
          </button>
        </form>
      )}
      <Link to="/login">Back to sign in</Link>
    </AuthFrame>
  )
}
