import clsx from 'clsx'
import { formatPercent } from '@/lib/format'
import type { Tone } from '../status'
import styles from './ConfidenceBand.module.css'

export type ConfidenceLevel = 'high' | 'medium' | 'low'

export const CONFIDENCE_THRESHOLDS = { high: 0.9, medium: 0.7 } as const

const META: Record<ConfidenceLevel, { label: string; tone: Tone; bars: number }> = {
  high: { label: 'Alta', tone: 'ok', bars: 3 },
  medium: { label: 'Media', tone: 'warn', bars: 2 },
  low: { label: 'Baja', tone: 'danger', bars: 1 },
}

/** ≥ 0.9 high, ≥ 0.7 medium, otherwise low; null when unknown. */
export function confidenceLevel(value: number | null | undefined): ConfidenceLevel | null {
  if (value == null || !Number.isFinite(value)) return null
  if (value >= CONFIDENCE_THRESHOLDS.high) return 'high'
  if (value >= CONFIDENCE_THRESHOLDS.medium) return 'medium'
  return 'low'
}

export function confidenceLabel(level: ConfidenceLevel): string {
  return META[level].label
}

export interface ConfidenceBandProps {
  /** Probability 0..1 that the decision is right. Renders nothing when null. */
  value: number | null | undefined
  /** Also print the percentage. */
  showValue?: boolean
  className?: string
}

export function ConfidenceBand({ value, showValue, className }: ConfidenceBandProps) {
  const level = confidenceLevel(value)
  if (!level || value == null) return null
  const meta = META[level]
  const pct = formatPercent(value, { decimals: 0 })
  return (
    <span className={clsx(styles.band, className)} data-tone={meta.tone} title={`Confianza ${meta.label.toLowerCase()} (${pct})`}>
      <span className={styles.bars} aria-hidden>
        {[1, 2, 3].map((i) => (
          <span key={i} className={clsx(styles.bar, i <= meta.bars && styles.on)} />
        ))}
      </span>
      <span className={styles.label}>{meta.label}</span>
      {showValue && <span className={clsx(styles.value, 'tabular')}>{pct}</span>}
    </span>
  )
}
