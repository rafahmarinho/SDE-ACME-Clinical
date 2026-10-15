import { useQuery } from '@tanstack/react-query'
import { AlertOctagon, ChevronDown, LogOut, Settings, UserRound } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet } from 'react-router'
import { useAuth } from '../hooks/useAuth'
import { useLiveStatus } from '../hooks/useLive'
import { useToast } from '../hooks/useToast'
import { fmtTime, ROLE_LABELS } from '../lib/format'
import { visibleNav } from '../lib/navigation'
import { errorMessage } from '../services/api'
import { Api } from '../services/endpoints'
import { Avatar, Modal } from './ui'

function Logo() {
  return (
    <span className="brand-mark" aria-hidden>
      <svg width="22" height="22" viewBox="0 0 32 32">
        <path d="M3 17h6l2.5-6 4 12 3-9 2 3H29" fill="none" stroke="#5eead4" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    </span>
  )
}

function LiveIndicator() {
  const status = useLiveStatus()
  const label = status === 'live' ? 'Live' : status === 'polling' ? 'Live updates degraded · polling' : 'Connecting'
  const cls = status === 'live' ? 'badge-ok' : status === 'polling' ? 'badge-warning' : 'badge-muted'
  return (
    <span className={`badge ${cls}`} title="Real-time connection status">
      <span className={`dot${status === 'live' ? ' pulse' : ''}`} /> {label}
    </span>
  )
}

function beep() {
  try {
    const ctx = new AudioContext()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.frequency.value = 960
    gain.gain.value = 0.08
    osc.connect(gain).connect(ctx.destination)
    osc.start()
    osc.stop(ctx.currentTime + 0.35)
  } catch {
    /* audio not available */
  }
}

function UserMenu() {
  const { me, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])
  if (!me) return null
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button className="btn btn-ghost" onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}>
        <Avatar name={me.full_name} url={me.avatar_url} />
        <span style={{ textAlign: 'left', lineHeight: 1.2 }}>
          <span style={{ display: 'block', fontWeight: 650 }}>{me.full_name}</span>
          <span className="muted small">{ROLE_LABELS[me.role]}</span>
        </span>
        <ChevronDown size={16} />
      </button>
      {open && (
        <div className="menu" role="menu">
          <Link to="/profile" role="menuitem" onClick={() => setOpen(false)}>
            <UserRound size={16} /> Profile
          </Link>
          <Link to="/settings" role="menuitem" onClick={() => setOpen(false)}>
            <Settings size={16} /> Settings
          </Link>
          <button role="menuitem" onClick={() => void signOut()}>
            <LogOut size={16} /> Sign out
          </button>
        </div>
      )}
    </div>
  )
}

function ConsentGate() {
  const { me, refresh, signOut } = useAuth()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  if (!me?.consent.required) return null
  const accept = async () => {
    setBusy(true)
    try {
      await Api.acceptConsent(me.consent.current_version)
      await refresh()
    } catch (err) {
      toast(errorMessage(err), 'error')
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal
      title="Before you continue"
      onClose={() => undefined}
      dismissible={false}
      footer={
        <>
          <button className="btn" onClick={() => void signOut()}>
            Decline and sign out
          </button>
          <button className="btn btn-primary" onClick={accept} disabled={busy}>
            I understand and agree
          </button>
        </>
      }
    >
      <p>
        <strong>Authorized clinical use only.</strong> ACME Clinical processes health information about patients and personal data about
        staff (name, contact details, sign-in activity and actions) to provide patient monitoring and to keep an audit trail required for
        patient safety.
      </p>
      <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
        <li>Access only the patients you care for. Every view and change is recorded.</li>
        <li>You can review and download your personal data, and request its removal, in Settings › Privacy.</li>
        <li>Patient data in this demonstration is entirely fictional.</li>
      </ul>
      <p className="muted small">Privacy notice version {me.consent.current_version}.</p>
    </Modal>
  )
}

export function AppLayout() {
  const { me } = useAuth()
  const nav = visibleNav(me?.permissions ?? [])
  const overview = useQuery({ queryKey: ['overview'], queryFn: Api.overview, enabled: !!me, refetchInterval: 30_000 })
  const critical = overview.data?.beds.filter((b) => (b.alarms ?? []).some((a) => a.severity === 'critical' && !a.acknowledged)) ?? []
  const lastCount = useRef(0)

  useEffect(() => {
    if (critical.length > lastCount.current && me?.preferences.alarm_sound) beep()
    lastCount.current = critical.length
  }, [critical.length, me?.preferences.alarm_sound])

  const sections = ['Care', 'Equipment', 'Administration'] as const
  const sim = overview.data?.simulation
  const unacked = overview.data?.kpis.unacknowledged ?? 0

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <Logo />
          <div>
            <div className="brand-name">ACME Clinical</div>
            <div className="brand-sub">{me?.unit ?? 'Ward 4B'} · Patient monitoring</div>
          </div>
        </div>
        <nav className="nav" aria-label="Main">
          {sections.map((section) => {
            const items = nav.filter((n) => n.section === section)
            if (!items.length) return null
            return (
              <div key={section}>
                <div className="nav-section">{section}</div>
                {items.map((item) => (
                  <NavLink key={item.to} to={item.to} end={item.to === '/'}>
                    <item.icon size={18} />
                    {item.label}
                    {item.to === '/alarms' && unacked > 0 && <span className="count">{unacked}</span>}
                  </NavLink>
                ))}
              </div>
            )
          })}
        </nav>
        <div className="sidebar-foot">
          Simulation environment · fictional data
          <br />
          ACME Clinical v1.0
        </div>
      </aside>
      <div className="main">
        {me?.preferences.critical_banner && critical.length > 0 && (
          <div className="banner-critical" role="alert">
            <AlertOctagon size={18} className="pulse" />
            {critical.length} bed{critical.length > 1 ? 's' : ''} with unacknowledged critical alarms:{' '}
            {critical.map((b) => b.label).join(', ')}
            <span style={{ flex: 1 }} />
            <Link to="/alarms">Review alarms</Link>
          </div>
        )}
        <header className="topbar">
          <LiveIndicator />
          {sim && (
            <span className="pill num" title="Simulated clock">
              Sim t={sim.tick} · {fmtTime(sim.sim_time)}
            </span>
          )}
          <span className="spacer" />
          <UserMenu />
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
      <ConsentGate />
    </div>
  )
}
