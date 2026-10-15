import { AlertTriangle, Eye, EyeOff, Inbox, RefreshCw, X } from 'lucide-react'
import { type ReactNode, useEffect, useId, useState } from 'react'
import { errorMessage } from '../services/api'
import type { Severity } from '../services/types'

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <span className="row muted small" role="status">
      <span className="spinner" aria-hidden />
      {label}…
    </span>
  )
}

export function Skeleton({ height = 18, width = '100%' }: { height?: number; width?: number | string }) {
  return <div className="skeleton" style={{ height, width }} aria-hidden />
}

export function LoadingCards({ count = 6, height = 150 }: { count?: number; height?: number }) {
  return (
    <div className="beds" aria-busy="true">
      {Array.from({ length: count }, (_, i) => (
        <Skeleton key={i} height={height} />
      ))}
    </div>
  )
}

export function EmptyState({ title, children, icon }: { title: string; children?: ReactNode; icon?: ReactNode }) {
  return (
    <div className="empty">
      {icon ?? <Inbox size={28} />}
      <strong>{title}</strong>
      {children && <div className="small">{children}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div className="alert alert-error" role="alert">
      <AlertTriangle size={18} />
      <div className="stack" style={{ gap: 6 }}>
        <span>{errorMessage(error)}</span>
        {onRetry && (
          <button type="button" className="btn btn-sm" onClick={onRetry}>
            <RefreshCw size={14} /> Try again
          </button>
        )}
      </div>
    </div>
  )
}

export function SeverityBadge({ severity }: { severity: Severity | null | undefined }) {
  if (!severity) return <span className="badge badge-ok">Normal</span>
  const label = severity === 'critical' ? 'Critical' : severity === 'warning' ? 'Warning' : 'Advisory'
  return (
    <span className={`badge badge-${severity}`}>
      <span className={`dot${severity === 'critical' ? ' pulse' : ''}`} />
      {label}
    </span>
  )
}

export function Modal({
  title,
  onClose,
  children,
  footer,
  dismissible = true,
}: {
  title: string
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
  dismissible?: boolean
}) {
  const id = useId()
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => dismissible && e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, dismissible])
  return (
    <div className="modal-backdrop" onMouseDown={(e) => dismissible && e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby={id}>
        <div className="modal-head">
          <h2 id={id}>{title}</h2>
          {dismissible && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close">
              <X size={18} />
            </button>
          )}
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  )
}

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string
  hint?: ReactNode
  error?: string | null
  children: ReactNode
  htmlFor?: string
}) {
  return (
    <div className="field">
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && !error && <span className="hint">{hint}</span>}
      {error && <span className="error">{error}</span>}
    </div>
  )
}

export function PasswordInput({
  id,
  value,
  onChange,
  autoComplete,
  required = true,
}: {
  id: string
  value: string
  onChange: (v: string) => void
  autoComplete: 'current-password' | 'new-password'
  required?: boolean
}) {
  const [show, setShow] = useState(false)
  return (
    <div className="input-group">
      <input
        id={id}
        className="input"
        type={show ? 'text' : 'password'}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        required={required}
        maxLength={128}
        spellCheck={false}
        style={{ paddingRight: 44 }}
      />
      <button type="button" className="btn btn-ghost" onClick={() => setShow((s) => !s)} aria-label={show ? 'Hide password' : 'Show password'}>
        {show ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  )
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (pages <= 1) return null
  return (
    <div className="row" style={{ justifyContent: 'flex-end', padding: '10px 14px' }}>
      <span className="muted small">
        Page {page} of {pages} · {total} results
      </span>
      <button className="btn btn-sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>
        Previous
      </button>
      <button className="btn btn-sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>
        Next
      </button>
    </div>
  )
}

export function Avatar({ name, url, size }: { name: string; url?: string | null; size?: 'lg' }) {
  const text = name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join('')
  return <span className={`avatar${size === 'lg' ? ' lg' : ''}`}>{url ? <img src={url} alt="" referrerPolicy="no-referrer" /> : text}</span>
}

export function ConfirmDialog({
  title,
  body,
  confirmLabel,
  danger,
  busy,
  onConfirm,
  onClose,
  requireText,
}: {
  title: string
  body: ReactNode
  confirmLabel: string
  danger?: boolean
  busy?: boolean
  onConfirm: () => void
  onClose: () => void
  requireText?: string
}) {
  const [typed, setTyped] = useState('')
  const blocked = !!requireText && typed !== requireText
  return (
    <Modal
      title={title}
      onClose={onClose}
      footer={
        <>
          <button className="btn" onClick={onClose} disabled={busy}>
            Cancel
          </button>
          <button className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} onClick={onConfirm} disabled={busy || blocked}>
            {busy ? 'Working…' : confirmLabel}
          </button>
        </>
      }
    >
      <div>{body}</div>
      {requireText && (
        <Field label={`Type ${requireText} to confirm`} htmlFor="confirm-text">
          <input id="confirm-text" className="input" value={typed} onChange={(e) => setTyped(e.target.value)} autoComplete="off" />
        </Field>
      )}
    </Modal>
  )
}
