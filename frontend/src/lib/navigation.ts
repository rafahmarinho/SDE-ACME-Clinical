import {
  Activity,
  BellRing,
  Boxes,
  ClipboardList,
  FileBarChart,
  FlaskConical,
  LayoutDashboard,
  type LucideIcon,
  ScrollText,
  SlidersHorizontal,
  Users,
} from 'lucide-react'

export interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  permission: string
  section: 'Care' | 'Equipment' | 'Administration'
}

/** Navigation adapts to the permissions the API reports for the signed-in role. */
export const NAV_ITEMS: NavItem[] = [
  { to: '/', label: 'Ward overview', icon: LayoutDashboard, permission: 'ward:view', section: 'Care' },
  { to: '/patients', label: 'Patients', icon: ClipboardList, permission: 'patients:view', section: 'Care' },
  { to: '/monitoring', label: 'Live monitoring', icon: Activity, permission: 'vitals:view', section: 'Care' },
  { to: '/alarms', label: 'Alarms', icon: BellRing, permission: 'alarms:view', section: 'Care' },
  { to: '/thresholds', label: 'Alarm limits', icon: SlidersHorizontal, permission: 'thresholds:view', section: 'Care' },
  { to: '/devices', label: 'Devices', icon: Boxes, permission: 'devices:view', section: 'Equipment' },
  { to: '/reports', label: 'Reports', icon: FileBarChart, permission: 'reports:devices', section: 'Equipment' },
  { to: '/simulation', label: 'Simulation', icon: FlaskConical, permission: 'simulation:view', section: 'Equipment' },
  { to: '/team', label: 'Team', icon: Users, permission: 'team:manage', section: 'Administration' },
  { to: '/audit', label: 'Audit log', icon: ScrollText, permission: 'audit:view', section: 'Administration' },
]

export function visibleNav(permissions: string[]): NavItem[] {
  const set = new Set(permissions)
  return NAV_ITEMS.filter((item) => set.has(item.permission))
}

/** Only same-app paths are accepted as post-login destinations (no open redirects). */
export function safeInternalPath(value: string | null | undefined, fallback = '/'): string {
  if (!value || !value.startsWith('/') || value.startsWith('//') || value.includes('\\') || /[\u0000-\u001f]/.test(value)) {
    return fallback
  }
  try {
    const url = new URL(value, 'https://app.invalid')
    return url.origin === 'https://app.invalid' ? `${url.pathname}${url.search}` : fallback
  } catch {
    return fallback
  }
}
