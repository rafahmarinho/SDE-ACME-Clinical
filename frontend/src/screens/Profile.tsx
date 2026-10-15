import { Trash2, Upload } from 'lucide-react'
import { type ChangeEvent, type FormEvent, useRef, useState } from 'react'
import { Avatar, Field } from '../components/ui'
import { useAuth } from '../hooks/useAuth'
import { useToast } from '../hooks/useToast'
import { fmtDate, fmtDateTime, ROLE_LABELS } from '../lib/format'
import { errorMessage } from '../services/api'
import { Api } from '../services/endpoints'

export default function Profile() {
  const { me, refresh } = useAuth()
  const toast = useToast()
  const fileRef = useRef<HTMLInputElement>(null)
  const [form, setForm] = useState({ full_name: me?.full_name ?? '', job_title: me?.job_title ?? '', phone: me?.phone ?? '' })
  const [busy, setBusy] = useState(false)
  const [uploading, setUploading] = useState(false)
  if (!me) return null

  const save = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      await Api.updateProfile({ full_name: form.full_name.trim(), job_title: form.job_title.trim(), phone: form.phone.trim() })
      await refresh()
      toast('Profile saved.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBusy(false)
    }
  }

  const upload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
      toast('Choose a PNG, JPEG or WebP image.', 'error')
      return
    }
    if (file.size > 2 * 1024 * 1024) {
      toast('The image must be 2 MB or smaller.', 'error')
      return
    }
    setUploading(true)
    try {
      await Api.uploadAvatar(file)
      await refresh()
      toast('Photo updated.', 'success')
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setUploading(false)
    }
  }

  const removePhoto = async () => {
    try {
      await Api.deleteAvatar()
      await refresh()
    } catch (err) {
      toast(errorMessage(err), 'error')
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Profile</h1>
          <p>Keep your details accurate — colleagues see your name on notes and alarm acknowledgements.</p>
        </div>
      </div>
      <div className="split">
        <form className="card card-pad stack" onSubmit={save}>
          <h2>Personal details</h2>
          <Field label="Full name" htmlFor="name" hint="Letters, spaces, hyphens and apostrophes.">
            <input id="name" className="input" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required maxLength={120} autoComplete="name" />
          </Field>
          <div className="grid grid-2">
            <Field label="Job title" htmlFor="title">
              <input id="title" className="input" value={form.job_title} onChange={(e) => setForm({ ...form, job_title: e.target.value })} maxLength={80} autoComplete="organization-title" />
            </Field>
            <Field label="Phone / pager" htmlFor="phone">
              <input id="phone" className="input" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} maxLength={24} autoComplete="tel" inputMode="tel" />
            </Field>
          </div>
          <Field label="E-mail" htmlFor="email" hint="Managed by your administrator.">
            <input id="email" className="input" value={me.email} disabled />
          </Field>
          <div>
            <button className="btn btn-primary" disabled={busy}>
              {busy ? 'Saving…' : 'Save changes'}
            </button>
          </div>
        </form>
        <div className="stack">
          <div className="card card-pad stack" style={{ alignItems: 'center', textAlign: 'center' }}>
            <Avatar name={me.full_name} url={me.avatar_url} size="lg" />
            <div>
              <strong>{me.full_name}</strong>
              <div className="muted small">
                {ROLE_LABELS[me.role]} · {me.unit}
              </div>
            </div>
            <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={upload} />
            <div className="row" style={{ justifyContent: 'center' }}>
              <button className="btn btn-sm" onClick={() => fileRef.current?.click()} disabled={uploading}>
                <Upload size={14} /> {uploading ? 'Uploading…' : 'Upload photo'}
              </button>
              {me.avatar_url && (
                <button className="btn btn-sm btn-ghost" onClick={removePhoto}>
                  <Trash2 size={14} /> Remove
                </button>
              )}
            </div>
            <span className="muted small">PNG, JPEG or WebP, up to 2 MB. Stored privately.</span>
          </div>
          <div className="card card-pad stack small">
            <h3>Account</h3>
            <div>Member since {fmtDate(me.created_at)}</div>
            <div>
              Previous sign-in: {fmtDateTime(me.previous_sign_in.at)} {me.previous_sign_in.ip ? `from ${me.previous_sign_in.ip}` : ''}
            </div>
            <div>Two-factor authentication: {me.session.mfa_enrolled ? 'on' : 'off'}</div>
          </div>
        </div>
      </div>
    </>
  )
}
