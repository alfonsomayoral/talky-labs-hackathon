import { toneColor, type Tone } from '../status'

export interface SparklineProps {
  values: number[]
  width?: number
  height?: number
  /** Default `neutral` (gray line). */
  tone?: Tone
  /** Soft fill under the line. */
  area?: boolean
  /** Dot on the last value. Default true. */
  showLast?: boolean
  /** Describe the trend for screen readers; without it the chart is decorative. */
  'aria-label'?: string
  className?: string
}

const PAD = 2

/** Tiny inline trend (e.g. a vendor's monthly history next to the accrual estimate). */
export function Sparkline({ values, width = 80, height = 24, tone = 'neutral', area, showLast = true, className, ...aria }: SparklineProps) {
  if (values.length === 0) return null
  const color = tone === 'neutral' ? 'var(--ink-3)' : toneColor(tone)
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = max - min || 1
  const stepX = values.length > 1 ? (width - PAD * 2) / (values.length - 1) : 0
  const points = values.map((v, i) => {
    const x = values.length > 1 ? PAD + i * stepX : width / 2
    const y = max === min ? height / 2 : PAD + (1 - (v - min) / span) * (height - PAD * 2)
    return [x, y] as const
  })
  const line = points.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const [lastX, lastY] = points[points.length - 1]
  const label = aria['aria-label']

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className={className}
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      style={{ overflow: 'visible' }}
    >
      {area && <polygon points={`${points[0][0]},${height} ${line} ${lastX},${height}`} fill={color} fillOpacity={0.1} />}
      <polyline points={line} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
      {showLast && <circle cx={lastX} cy={lastY} r={2} fill={color} />}
    </svg>
  )
}
