import type { ReactNode } from 'react'

export function AuthFrame({ children }: { children: ReactNode }) {
  return (
    <div className="auth-page">
      <section className="auth-hero">
        <div className="row" style={{ gap: 12 }}>
          <span className="brand-mark" style={{ background: '#13294b' }}>
            <svg width="22" height="22" viewBox="0 0 32 32" aria-hidden>
              <path d="M3 17h6l2.5-6 4 12 3-9 2 3H29" fill="none" stroke="#5eead4" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <strong style={{ fontSize: '1.1rem' }}>ACME Clinical</strong>
        </div>
        <div>
          <h1>Every bed, every beat, one calm view.</h1>
          <p>Central monitoring for Ward 4B: live vital signs, alarms that stay visible until the problem is solved, and device care in one place.</p>
        </div>
        <svg className="trace" viewBox="0 0 600 80" preserveAspectRatio="none" aria-hidden>
          <path
            d="M0 50 H120 l10 -6 l8 6 H170 l6 10 l10 -52 l10 62 l8 -20 H290 l10 -6 l8 6 H340 l6 10 l10 -52 l10 62 l8 -20 H460 l10 -6 l8 6 H510 l6 10 l10 -52 l10 62 l8 -20 H600"
            fill="none"
            stroke="#5eead4"
            strokeWidth="2.5"
          />
        </svg>
        <p className="small" style={{ color: '#9fb1cc' }}>
          Demonstration system with fictional patients and simulated monitors. Not for clinical use.
        </p>
      </section>
      <section className="auth-panel">
        <div className="auth-card">{children}</div>
      </section>
    </div>
  )
}
