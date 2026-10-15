import { ShieldCheck } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { Link, Navigate, useLocation } from 'react-router'
import { Field, PasswordInput } from '../../components/ui'
import { useAuth } from '../../hooks/useAuth'
import { safeInternalPath } from '../../lib/navigation'
import { ApiError, errorMessage } from '../../services/api'
import { AuthFrame } from './AuthFrame'

export default function Login() {
  const { status, me, signIn, verifyMfa, notice, clearNotice, signOut } = useAuth()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (status === 'ready' && me) {
    const from = (location.state as { from?: string } | null)?.from
    return <Navigate to={safeInternalPath(from, me.preferences.landing_page)} replace />
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    clearNotice()
    try {
      await signIn(email.trim(), password)
      setPassword('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const submitCode = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await verifyMfa(code.trim())
    } catch (err) {
      setError(err instanceof Error ? err.message : errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (status === 'mfa') {
    return (
      <AuthFrame>
        <div className="stack" style={{ gap: 6 }}>
          <ShieldCheck size={28} color="#0e7c86" />
          <h1>Two-factor authentication</h1>
          <p className="muted">Enter the 6-digit code from your authenticator app.</p>
        </div>
        {error && (
          <div className="alert alert-error" role="alert">
            {error}
          </div>
        )}
        <form className="stack" onSubmit={submitCode}>
          <Field label="Authentication code" htmlFor="code">
            <input
              id="code"
              className="input num"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))}
              required
              autoFocus
              style={{ fontSize: '1.6rem', letterSpacing: '0.4em', textAlign: 'center' }}
            />
          </Field>
          <button className="btn btn-primary btn-lg btn-block" disabled={busy || code.length !== 6}>
            {busy ? 'Verifying…' : 'Verify'}
          </button>
          <button type="button" className="btn btn-ghost" onClick={() => void signOut()}>
            Use a different account
          </button>
        </form>
      </AuthFrame>
    )
  }

  return (
    <AuthFrame>
      <div className="stack" style={{ gap: 6 }}>
        <h1>Sign in</h1>
        <p className="muted">Use your ACME Clinical staff account.</p>
      </div>
      {notice && (
        <div className="alert alert-info" role="status">
          {notice}
        </div>
      )}
      {error && (
        <div className="alert alert-error" role="alert">
          {error}
        </div>
      )}
      <form className="stack" onSubmit={submit} noValidate={false}>
        <Field label="Work e-mail" htmlFor="email">
          <input
            id="email"
            className="input"
            type="email"
            autoComplete="username"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            maxLength={254}
            autoFocus
          />
        </Field>
        <Field label="Password" htmlFor="password">
          <PasswordInput id="password" value={password} onChange={setPassword} autoComplete="current-password" />
        </Field>
        <div className="row" style={{ justifyContent: 'flex-end' }}>
          <Link to="/forgot-password" className="small">
            Forgot your password?
          </Link>
        </div>
        <button className="btn btn-primary btn-lg btn-block" disabled={busy || status === 'loading'}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
      <p className="notice">
        <strong>Authorized users only.</strong> This system contains confidential health information. Activity is monitored and recorded;
        unauthorized access is prohibited and may be reported.
      </p>
    </AuthFrame>
  )
}
