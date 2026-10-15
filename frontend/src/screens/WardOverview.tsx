import { useQuery } from '@tanstack/react-query'
import { Box, LayoutGrid } from 'lucide-react'
import { lazy, Suspense, useState } from 'react'
import { BedCard } from '../components/BedCard'
import { ErrorState, LoadingCards, Skeleton } from '../components/ui'
import { useAuth } from '../hooks/useAuth'
import { fmtDateTime, relative } from '../lib/format'
import { Api } from '../services/endpoints'

const Ward3D = lazy(() => import('../components/Ward3D'))

function Kpi({ label, value, tone }: { label: string; value: number | undefined; tone?: 'critical' | 'warning' }) {
  return (
    <div className={`card kpi${tone && value ? ` ${tone}` : ''}`}>
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value ?? '–'}</span>
    </div>
  )
}

export default function WardOverview() {
  const { me, can } = useAuth()
  const [view, setView] = useState<'grid' | '3d'>(me?.preferences.ward_view ?? 'grid')
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ['overview'], queryFn: Api.overview })
  const clinical = can('vitals:view')
  const k = data?.kpis

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Ward 4B overview</h1>
          <p>
            {data?.simulation ? `Last update ${relative(data.simulation.sim_time)} · ${fmtDateTime(data.simulation.sim_time)}` : 'Real-time status of every bed'}
            {me?.previous_sign_in.at && ` · Your previous sign-in: ${fmtDateTime(me.previous_sign_in.at)}${me.previous_sign_in.ip ? ` from ${me.previous_sign_in.ip}` : ''}`}
          </p>
        </div>
        <div className="row" role="group" aria-label="View">
          <button className={`btn${view === 'grid' ? ' btn-primary' : ''}`} onClick={() => setView('grid')}>
            <LayoutGrid size={16} /> Beds
          </button>
          <button className={`btn${view === '3d' ? ' btn-primary' : ''}`} onClick={() => setView('3d')}>
            <Box size={16} /> 3D ward
          </button>
        </div>
      </div>

      <div className="grid grid-4">
        {clinical ? (
          <>
            <Kpi label="Patients" value={k?.patients} />
            <Kpi label="Monitored now" value={k?.monitored} />
            <Kpi label="Critical alarms" value={k?.critical} tone="critical" />
            <Kpi label="Unacknowledged" value={k?.unacknowledged} tone="warning" />
          </>
        ) : (
          <>
            <Kpi label="Monitors offline" value={k?.offline} tone="critical" />
            <Kpi label="Low battery" value={k?.low_battery} tone="warning" />
            <Kpi label="Maintenance due" value={k?.maintenance_due} tone="warning" />
            <Kpi label="Open tickets" value={k?.open_tickets} />
          </>
        )}
      </div>

      {error && <ErrorState error={error} onRetry={() => void refetch()} />}
      {isLoading && (view === 'grid' ? <LoadingCards count={12} /> : <Skeleton height={560} />)}
      {data &&
        (view === 'grid' ? (
          <div className="beds">
            {data.beds.map((bed) => (
              <BedCard key={bed.bed_id} bed={bed} showClinical={clinical} />
            ))}
          </div>
        ) : (
          <Suspense fallback={<Skeleton height={560} />}>
            <Ward3D beds={data.beds} showClinical={clinical} />
          </Suspense>
        ))}
    </>
  )
}
