import { fmtTime } from '../lib/format'

interface Series {
  key: string
  label: string
  color: string
  values: (number | null)[]
}

/** Lightweight SVG line chart with threshold bands. */
export function TrendChart({
  times,
  series,
  low,
  high,
  min,
  max,
  height = 160,
}: {
  times: string[]
  series: Series[]
  low?: number | null
  high?: number | null
  min: number
  max: number
  height?: number
}) {
  const width = 600
  const pad = { l: 34, r: 8, t: 8, b: 20 }
  const w = width - pad.l - pad.r
  const h = height - pad.t - pad.b
  const x = (i: number) => pad.l + (times.length <= 1 ? 0 : (i / (times.length - 1)) * w)
  const y = (v: number) => pad.t + h - ((Math.min(max, Math.max(min, v)) - min) / (max - min)) * h
  const ticks = [min, (min + max) / 2, max]

  const path = (values: (number | null)[]) => {
    let d = ''
    let pen = false
    values.forEach((v, i) => {
      if (v === null) {
        pen = false
        return
      }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)} `
      pen = true
    })
    return d
  }

  return (
    <svg className="chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ height }} role="img">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} stroke="#eef2f7" />
          <text x={pad.l - 6} y={y(t) + 4} fontSize="10" textAnchor="end" fill="#5b6b84">
            {Math.round(t)}
          </text>
        </g>
      ))}
      {high != null && <rect x={pad.l} y={pad.t} width={w} height={Math.max(0, y(high) - pad.t)} fill="#fde8e7" opacity="0.6" />}
      {low != null && <rect x={pad.l} y={y(low)} width={w} height={Math.max(0, pad.t + h - y(low))} fill="#fde8e7" opacity="0.6" />}
      {series.map((s) => (
        <path key={s.key} d={path(s.values)} fill="none" stroke={s.color} strokeWidth="2" vectorEffect="non-scaling-stroke" />
      ))}
      {times.length > 1 && (
        <>
          <text x={pad.l} y={height - 4} fontSize="10" fill="#5b6b84">
            {fmtTime(times[0])}
          </text>
          <text x={width - pad.r} y={height - 4} fontSize="10" fill="#5b6b84" textAnchor="end">
            {fmtTime(times[times.length - 1])}
          </text>
        </>
      )}
    </svg>
  )
}
