import { useQueryClient } from '@tanstack/react-query'
import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, onSessionProblem } from '../services/api'
import { heartbeat, signIn as apiSignIn, signOut as apiSignOut, verifyTotp } from '../services/auth'
import { Api } from '../services/endpoints'
import { supabase } from '../services/supabase'
import type { Me } from '../services/types'

type Status = 'loading' | 'signed_out' | 'mfa' | 'ready'

interface AuthState {
  status: Status
  me: Me | null
  notice: string | null
  signIn: (email: string, password: string) => Promise<void>
  verifyMfa: (code: string) => Promise<void>
  signOut: (notice?: string, revoke?: boolean) => Promise<void>
  refresh: () => Promise<void>
  can: (permission: string) => boolean
  clearNotice: () => void
}

const AuthContext = createContext<AuthState | null>(null)

const ACTIVITY_EVENTS = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<Status>('loading')
  const [me, setMe] = useState<Me | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const lastActivity = useRef(Date.now())
  const lastHeartbeat = useRef(0)

  const loadMe = useCallback(async () => {
    const profile = await Api.me()
    setMe(profile)
    setStatus('ready')
    document.body.classList.toggle('compact', profile.preferences.density === 'compact')
  }, [])

  const signOut = useCallback(
    async (message?: string, revoke = true) => {
      await apiSignOut(revoke)
      queryClient.clear()
      setMe(null)
      setStatus('signed_out')
      if (message) setNotice(message)
    },
    [queryClient],
  )

  // Initial session (survives a page reload within the same tab).
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const { data } = await supabase.auth.getSession()
      if (!data.session) {
        if (!cancelled) setStatus('signed_out')
        return
      }
      try {
        await loadMe()
      } catch (err) {
        if (cancelled) return
        if (err instanceof ApiError && err.code === 'mfa_required') setStatus('mfa')
        else if (!(err instanceof ApiError && err.status === 401)) setStatus('signed_out')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [loadMe])

  // Expired, revoked or step-up sessions reported by the API.
  useEffect(() => {
    onSessionProblem((code, message) => {
      if (code === 'mfa_required') {
        setStatus('mfa')
        return
      }
      void signOut(message, false)
    })
    return () => onSessionProblem(null)
  }, [signOut])

  // Idle timeout: activity keeps the server session alive; inactivity signs out locally too.
  useEffect(() => {
    if (status !== 'ready' || !me) return
    const idleMs = (me.session.idle_timeout_seconds ?? 900) * 1000
    const onActivity = () => {
      lastActivity.current = Date.now()
      if (Date.now() - lastHeartbeat.current > 60_000) {
        lastHeartbeat.current = Date.now()
        heartbeat().catch(() => undefined)
      }
    }
    ACTIVITY_EVENTS.forEach((e) => window.addEventListener(e, onActivity, { passive: true }))
    const timer = window.setInterval(() => {
      if (Date.now() - lastActivity.current > idleMs) {
        void signOut('You were signed out after a period of inactivity.')
      }
    }, 15_000)
    return () => {
      ACTIVITY_EVENTS.forEach((e) => window.removeEventListener(e, onActivity))
      window.clearInterval(timer)
    }
  }, [status, me, signOut])

  const signIn = useCallback(
    async (email: string, password: string) => {
      setNotice(null)
      const result = await apiSignIn(email, password)
      lastActivity.current = Date.now()
      lastHeartbeat.current = Date.now()
      if (result.mfaRequired) {
        setStatus('mfa')
        return
      }
      await loadMe()
    },
    [loadMe],
  )

  const verifyMfa = useCallback(
    async (code: string) => {
      await verifyTotp(code)
      await loadMe()
    },
    [loadMe],
  )

  const value = useMemo<AuthState>(
    () => ({
      status,
      me,
      notice,
      signIn,
      verifyMfa,
      signOut,
      refresh: loadMe,
      can: (permission: string) => !!me?.permissions.includes(permission),
      clearNotice: () => setNotice(null),
    }),
    [status, me, notice, signIn, verifyMfa, signOut, loadMe],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}
