import type { RealtimeChannel } from '@supabase/supabase-js'
import { supabase } from './supabase'

export type RealtimeStatus = 'connecting' | 'live' | 'polling'

const TABLES = ['monitors', 'alarms', 'vital_readings', 'patients', 'notes', 'maintenance_records', 'sim_state', 'sim_events', 'thresholds']

/**
 * Subscribes to row changes the signed-in user may read (RLS decides). Payloads are only used as a
 * signal to refetch through the API, so encrypted or filtered columns never reach the UI from here.
 */
export function subscribeWard(onChange: (table: string) => void, onStatus: (status: RealtimeStatus) => void): () => void {
  let channel: RealtimeChannel | null = supabase.channel('ward-4b')
  for (const table of TABLES) {
    channel = channel.on('postgres_changes', { event: '*', schema: 'public', table }, () => onChange(table))
  }
  let live = false
  channel.subscribe((status) => {
    live = status === 'SUBSCRIBED'
    if (live) onStatus('live')
    else if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT' || status === 'CLOSED') onStatus('polling')
  })
  // Degraded mode: if Realtime cannot connect, screens fall back to periodic polling.
  const timer = window.setTimeout(() => {
    if (!live) onStatus('polling')
  }, 8000)
  return () => {
    window.clearTimeout(timer)
    if (channel) void supabase.removeChannel(channel)
    channel = null
  }
}
