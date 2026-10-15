import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Download, ShieldCheck } from 'lucide-react'
import { Link, useParams } from 'react-router'
import { ErrorState, Skeleton } from '../components/ui'
import { useToast } from '../hooks/useToast'
import { bytes, fmtDateTime } from '../lib/format'
import { download, errorMessage } from '../services/api'
import { Api } from '../services/endpoints'

function label(key: string): string {
  return key.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase())
}

function render(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([k, v]) => `${k} ${v ?? '—'}`)
      .join(' · ')
  }
  return String(value)
}

export default function ReportDetail() {
  const { id = '' } = useParams()
  const toast = useToast()
  const { data, error, isLoading, refetch } = useQuery({ queryKey: ['report', id], queryFn: () => Api.report(id) })
  if (error) return <ErrorState error={error} onRetry={() => void refetch()} />
  if (isLoading || !data) return <Skeleton height={400} />
  const { columns, preview, ...stats } = data.summary

  return (
    <>
      <Link to="/reports" className="row small">
        <ArrowLeft size={16} /> All reports
      </Link>
      <div className="page-head">
        <div>
          <h1>{data.title}</h1>
          <p>
            Generated {fmtDateTime(data.created_at)} by {data.created_by_name} · {data.row_count} rows · {bytes(data.size_bytes)}
          </p>
        </div>
        <button className="btn btn-primary" onClick={() => download(`/reports/${data.id}/download`, 'report.csv').catch((err) => toast(errorMessage(err), 'error'))}>
          <Download size={16} /> Download CSV
        </button>
      </div>
      <div className="grid grid-4">
        {Object.entries(stats).map(([k, v]) => (
          <div key={k} className="card kpi">
            <span className="kpi-label">{label(k)}</span>
            <span className="kpi-value" style={{ fontSize: typeof v === 'number' ? '2rem' : '1rem' }}>
              {render(v)}
            </span>
          </div>
        ))}
      </div>
      <div className="card">
        <div className="card-head">
          <h2>Preview</h2>
          <span className="muted small row" style={{ gap: 6 }}>
            <ShieldCheck size={14} /> SHA-256 <span className="mono">{data.sha256.slice(0, 16)}…</span>
          </span>
        </div>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c}>{label(c)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.map((row, i) => (
                <tr key={i}>
                  {columns.map((c) => (
                    <td key={c} className="small num">
                      {render(row[c])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.row_count > preview.length && <p className="card-body muted small">Showing the first {preview.length} rows. Download the CSV for the full report.</p>}
      </div>
    </>
  )
}
