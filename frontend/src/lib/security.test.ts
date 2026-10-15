import { describe, expect, it } from 'vitest'
import { safeInternalPath, visibleNav } from './navigation'
import { passwordIssues } from './password'

describe('safeInternalPath (open-redirect protection)', () => {
  it('keeps internal paths', () => {
    expect(safeInternalPath('/patients?x=1')).toBe('/patients?x=1')
  })
  it.each(['https://evil.example', '//evil.example', '/\\evil.example', 'javascript:alert(1)', '', null, '/\u0000x'])(
    'rejects %s',
    (value) => {
      expect(safeInternalPath(value as string | null, '/')).toBe('/')
    },
  )
})

describe('role-based navigation', () => {
  it('shows only permitted areas', () => {
    const biomed = visibleNav(['ward:view', 'alarms:view', 'devices:view', 'reports:devices', 'simulation:view']).map((n) => n.to)
    expect(biomed).toEqual(['/', '/alarms', '/devices', '/reports', '/simulation'])
    expect(visibleNav([])).toEqual([])
  })
})

describe('password hints', () => {
  it('flags weak passwords', () => {
    expect(passwordIssues('short')).toContain('at least 12 characters')
    expect(passwordIssues('Ward4B-Demo!2026')).toEqual([])
  })
})
