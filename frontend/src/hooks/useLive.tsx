import { useQueryClient } from '@tanstack/react-query'
import { createContext, type ReactNode, useContext, useEffect, useRef, useState } from 'react'
import { type RealtimeStatus, subscribeWard } from '../services/realtime'

const KEYS_BY_TABLE: Record<string, string[]> = {
  monitors: ['overview', 'devices', 'device', 'simState'],
  alarms: ['overview', 'alarms', 'patient', 'device'],
  vital_readings: ['overview', 'patient', 'vitals', 'patients'],
  patients: ['patients', 'patient', 'overview'],
  notes: ['notes'],
  maintenance_records: ['maintenance', 'device', 'devices'],
  sim_state: ['overview', 'simState'],
  sim_events: ['events', 'outbox'],
  thresholds: ['thresholds', 'patient'],
}
const POLL_KEYS = ['overview', 'alarms', 'patient', 'vitals', 'patients', 'devices', 'device', 'simState', 'events', 'maintenance']

const LiveContext = createContext<RealtimeStatus>('connecting')

/** Keeps every open screen current: Realtime pushes changes; if it is unavailable we poll (degraded mode). */
export function LiveProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [status, setStatus] = useState<RealtimeStatus>('connecting')
  const pending = useRef(new Set<string>())
  const timer = useRef<number | null>(null)

  useEffect(() => {
    const flush = () => {
      const keys = [...pending.current]
      pending.current.clear()
      timer.current = null
      keys.forEach((key) => void queryClient.invalidateQueries({ queryKey: [key] }))
    }
    return subscribeWard(
      (table) => {
        ;(KEYS_BY_TABLE[table] ?? []).forEach((k) => pending.current.add(k))
        if (timer.current === null) timer.current = window.setTimeout(flush, 400)
      },
      setStatus,
    )
  }, [queryClient])

  useEffect(() => {
    if (status !== 'polling') return
    const id = window.setInterval(() => {
      if (document.visibilityState !== 'visible') return
      POLL_KEYS.forEach((key) => void queryClient.invalidateQueries({ queryKey: [key] }))
    }, 5000)
    return () => window.clearInterval(id)
  }, [status, queryClient])

  return <LiveContext.Provider value={status}>{children}</LiveContext.Provider>
}

export const useLiveStatus = () => useContext(LiveContext)
