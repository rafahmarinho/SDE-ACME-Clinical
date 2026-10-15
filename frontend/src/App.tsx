import { Lock } from 'lucide-react'
import { lazy, type ReactNode, Suspense } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes, useLocation } from 'react-router'
import { AppLayout } from './components/AppLayout'
import { EmptyState, Spinner } from './components/ui'
import { useAuth } from './hooks/useAuth'
import { LiveProvider } from './hooks/useLive'
import ForgotPassword from './screens/auth/ForgotPassword'
import Login from './screens/auth/Login'
import ResetPassword from './screens/auth/ResetPassword'

const WardOverview = lazy(() => import('./screens/WardOverview'))
const Patients = lazy(() => import('./screens/Patients'))
const PatientDetail = lazy(() => import('./screens/PatientDetail'))
const LiveMonitoring = lazy(() => import('./screens/LiveMonitoring'))
const Alarms = lazy(() => import('./screens/Alarms'))
const Thresholds = lazy(() => import('./screens/Thresholds'))
const Devices = lazy(() => import('./screens/Devices'))
const DeviceDetail = lazy(() => import('./screens/DeviceDetail'))
const Reports = lazy(() => import('./screens/Reports'))
const ReportDetail = lazy(() => import('./screens/ReportDetail'))
const Simulation = lazy(() => import('./screens/Simulation'))
const Team = lazy(() => import('./screens/Team'))
const AuditLog = lazy(() => import('./screens/AuditLog'))
const Profile = lazy(() => import('./screens/Profile'))
const Settings = lazy(() => import('./screens/Settings'))

function FullPageLoader() {
  return (
    <div style={{ display: 'grid', placeItems: 'center', height: '100vh' }}>
      <Spinner label="Loading ACME Clinical" />
    </div>
  )
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <FullPageLoader />
  if (status !== 'ready') return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />
  return <LiveProvider>{children}</LiveProvider>
}

/** UX guard only: the API enforces every permission again on each request. */
function RequirePermission({ permission, children }: { permission: string; children: ReactNode }) {
  const { can } = useAuth()
  if (!can(permission)) {
    return (
      <EmptyState title="You do not have access to this page" icon={<Lock size={28} />}>
        Your role does not include this area. <Link to="/">Go to the ward overview</Link>.
      </EmptyState>
    )
  }
  return <>{children}</>
}

function NotFound() {
  return (
    <EmptyState title="Page not found">
      <Link to="/">Back to the ward overview</Link>
    </EmptyState>
  )
}

const guard = (permission: string, element: ReactNode) => <RequirePermission permission={permission}>{element}</RequirePermission>

export default function App() {
  return (
    <BrowserRouter>
      <Suspense fallback={<FullPageLoader />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/forgot-password" element={<ForgotPassword />} />
          <Route path="/reset-password" element={<ResetPassword mode="reset" />} />
          <Route path="/accept-invite" element={<ResetPassword mode="invite" />} />
          <Route
            element={
              <RequireAuth>
                <AppLayout />
              </RequireAuth>
            }
          >
            <Route index element={guard('ward:view', <WardOverview />)} />
            <Route path="patients" element={guard('patients:view', <Patients />)} />
            <Route path="patients/:id" element={<PatientDetail />} />
            <Route path="monitoring" element={guard('vitals:view', <LiveMonitoring />)} />
            <Route path="alarms" element={guard('alarms:view', <Alarms />)} />
            <Route path="thresholds" element={guard('thresholds:view', <Thresholds />)} />
            <Route path="devices" element={guard('devices:view', <Devices />)} />
            <Route path="devices/:id" element={guard('devices:view', <DeviceDetail />)} />
            <Route path="reports" element={guard('reports:devices', <Reports />)} />
            <Route path="reports/:id" element={guard('reports:devices', <ReportDetail />)} />
            <Route path="simulation" element={guard('simulation:view', <Simulation />)} />
            <Route path="team" element={guard('team:manage', <Team />)} />
            <Route path="audit" element={guard('audit:view', <AuditLog />)} />
            <Route path="profile" element={<Profile />} />
            <Route path="settings" element={<Settings />} />
            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  )
}
