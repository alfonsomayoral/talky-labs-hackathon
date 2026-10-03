import clsx from 'clsx'
import type { ItemStatus } from '@/domain/types'
import { formatNumber, formatPercent } from '@/lib/format'
import { ITEM_STATUS, ITEM_STATUS_ORDER, toneColor, type Tone } from '../status'
import styles from './ProgressBar.module.css'

export interface ProgressSegment {
  value: number
  tone: Tone
  label: string
}

export interface ProgressBarProps {
  /** Simple bar: progress `value` out of `max` (default 1). */
  value?: number
  max?: number
  tone?: Tone
  /** Stacked bar: one segment per category, in display order. Overrides `value`. */
  segments?: ProgressSegment[]
  /** Denominator for segments; defaults to their sum. */
  total?: number
  size?: 'sm' | 'md'
  /** Dot + label + count under a stacked bar. */
  showLegend?: boolean
  /** Accessible name. */
  label?: string
  className?: string
}

/** Segments for item statuses in canonical order (AUTO, NEEDS_HUMAN, BLOCKED, OPEN), zero counts dropped. */
export function statusSegments(counts: Partial<Record<ItemStatus, number>>): ProgressSegment[] {
  return ITEM_STATUS_ORDER.filter((s) => (counts[s] ?? 0) > 0).map((s) => ({
    value: counts[s] ?? 0,
    tone: ITEM_STATUS[s].tone,
    label: ITEM_STATUS[s].label,
  }))
}

export function ProgressBar({ value = 0, max = 1, tone = 'brand', segments, total, size = 'md', showLegend, label, className }: ProgressBarProps) {
  if (segments) {
    const sum = total ?? segments.reduce((acc, s) => acc + s.value, 0)
    const describe = segments.map((s) => `${s.label}: ${formatNumber(s.value)}`).join(', ')
    return (
      <div className={clsx(styles.wrap, className)}>
        <div className={clsx(styles.track, styles[size])} role="img" aria-label={label ? `${label}. ${describe}` : describe}>
          {sum > 0 &&
            segments.map((s) =>
              s.value > 0 ? (
                <span
                  key={s.label}
                  className={styles.segment}
                  style={{ width: `${(s.value / sum) * 100}%`, background: toneColor(s.tone) }}
                  title={`${s.label}: ${formatNumber(s.value)} (${formatPercent(s.value / sum)})`}
                />
              ) : null,
            )}
        </div>
        {showLegend && (
          <ul className={styles.legend}>
            {segments.map((s) => (
              <li key={s.label} className={styles.legendItem}>
                <span className={styles.legendDot} style={{ background: toneColor(s.tone) }} aria-hidden />
                <span>{s.label}</span>
                <span className={clsx(styles.legendCount, 'tabular')}>{formatNumber(s.value)}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    )
  }

  const ratio = max > 0 ? Math.min(Math.max(value / max, 0), 1) : 0
  return (
    <div
      className={clsx(styles.track, styles[size], className)}
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
    >
      <span className={styles.fill} style={{ width: `${ratio * 100}%`, background: toneColor(tone) }} />
    </div>
  )
}
