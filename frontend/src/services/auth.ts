import { api } from './api'
import { supabase } from './supabase'

export interface LoginResult {
  mfaRequired: boolean
  previousSignIn: { at: string | null; ip: string | null }
}

/** Sign in through the API (lockout, auditing, session limits) and hand the tokens to supabase-js. */
export async function signIn(email: string, password: string): Promise<LoginResult> {
  const result = await api<{
    access_token: string
    refresh_token: string
    mfa_required: boolean
    previous_sign_in: { at: string | null; ip: string | null }
  }>('/auth/login', { method: 'POST', body: { email, password }, auth: false })
  const { error } = await supabase.auth.setSession({ access_token: result.access_token, refresh_token: result.refresh_token })
  if (error) throw error
  return { mfaRequired: result.mfa_required, previousSignIn: result.previous_sign_in }
}

export async function verifyTotp(code: string): Promise<void> {
  const { data: factors, error } = await supabase.auth.mfa.listFactors()
  if (error) throw error
  const factor = factors.totp.find((f) => f.status === 'verified')
  if (!factor) throw new Error('No authenticator app is set up for this account.')
  const { error: verifyError } = await supabase.auth.mfa.challengeAndVerify({ factorId: factor.id, code })
  if (verifyError) throw new Error('That code is not valid. Check your authenticator app and try again.')
}

/** Removes every trace of the session and cached clinical data from the browser. */
export function clearBrowserData(): void {
  try {
    window.sessionStorage.clear()
    for (const key of Object.keys(window.localStorage)) {
      if (key.startsWith('acme-') || key.startsWith('sb-')) window.localStorage.removeItem(key)
    }
  } catch {
    /* storage unavailable */
  }
}

export async function signOut(callApi = true): Promise<void> {
  if (callApi) {
    try {
      await api('/auth/logout', { method: 'POST' })
    } catch {
      /* the session may already be gone */
    }
  }
  await supabase.auth.signOut({ scope: 'local' }).catch(() => undefined)
  supabase.removeAllChannels()
  clearBrowserData()
}

export const requestPasswordReset = (email: string) =>
  api<{ message: string }>('/auth/recover', { method: 'POST', body: { email }, auth: false })

export const completePasswordReset = (accessToken: string, newPassword: string) =>
  api<{ message: string }>('/auth/reset-password', {
    method: 'POST',
    body: { access_token: accessToken, new_password: newPassword },
    auth: false,
  })

export const heartbeat = () => api('/auth/heartbeat', { method: 'POST' })

export const syncMfa = () => api<{ mfa_enrolled: boolean }>('/auth/mfa/sync', { method: 'POST' })
