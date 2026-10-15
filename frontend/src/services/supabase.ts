import { createClient } from '@supabase/supabase-js'
import { config } from '../lib/config'

/**
 * Browser Supabase client (publishable key only).
 * - Session tokens live in sessionStorage: scoped to the tab, gone when it closes, never in cookies.
 * - Links from e-mails are handled explicitly by the reset/invite screens, not auto-detected.
 * - All writes go through the ACME Clinical API; the browser only reads via Realtime (RLS enforced).
 */
export const supabase = createClient(config.supabaseUrl, config.supabaseKey, {
  auth: {
    storage: window.sessionStorage,
    storageKey: 'acme-clinical-auth',
    persistSession: true,
    autoRefreshToken: true,
    detectSessionInUrl: false,
  },
  realtime: { params: { eventsPerSecond: 10 } },
})
