import { MailCheck } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { Link } from 'react-router'
import { Field } from '../../components/ui'
import { errorMessage } from '../../services/api'
import { requestPasswordReset } from '../../services/auth'
import { AuthFrame } from './AuthFrame'

export default function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const result = await requestPasswordReset(email.trim())
      setSent(result.message)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthFrame>
      <div className="stack" style={{ gap: 6 }}>
        <h1>Reset your password</h1>
        <p className="muted">We will e-mail you a single-use link that expires shortly.</p>
      </div>
      {sent ? (
        <div className="alert alert-success" role="status">
          <MailCheck size={18} />
          <span>{sent}</span>
        </div>
      ) : (
        <form className="stack" onSubmit={submit}>
          {error && (
            <div className="alert alert-error" role="alert">
              {error}
            </div>
          )}
          <Field label="Work e-mail" htmlFor="email">
            <input id="email" className="input" type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required maxLength={254} autoFocus />
          </Field>
          <button className="btn btn-primary btn-lg btn-block" disabled={busy}>
            {busy ? 'Sending…' : 'Send reset link'}
          </button>
        </form>
      )}
      <Link to="/login">Back to sign in</Link>
    </AuthFrame>
  )
}
