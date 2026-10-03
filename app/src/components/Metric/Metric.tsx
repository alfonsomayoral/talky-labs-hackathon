import type { ReactNode } from 'react'
import clsx from 'clsx'
import { Info } from 'lucide-react'
import { Skeleton } from '../Skeleton/Skeleton'
import { Tooltip } from '../Tooltip/Tooltip'
import styles from './Metric.module.css'

export interface MetricProps {
  label: ReactNode
  value: ReactNode
  /** Change against the comparison, already formatted (`+4,2 pp`, `−12`). */
  delta?: ReactNode
  /** Colour of the delta: `ok` good, `danger` bad, `neutral` informative. */
  deltaTone?: 'ok' | 'danger' | 'neutral'
  /** What the value is compared with (`vs. junio`, `de 305 partidas`). */
  comparison?: ReactNode
  /** Explanation of how the number is computed (info tooltip next to the label). */
  hint?: string
  size?: 'md' | 'lg'
  loading?: boolean
  className?: string
}

/** One headline number with its context. Use 3–4 in a row, inside Cards or a bordered strip. */
export function Metric({ label, value, delta, deltaTone = 'neutral', comparison, hint, size = 'md', loading, className }: MetricProps) {
  return (
    <div className={clsx(styles.metric, styles[size], className)}>
      <div className={styles.label}>
        <span>{label}</span>
        {hint && (
          <Tooltip content={hint}>
            <button type="button" className={styles.hint} aria-label={hint}>
              <Info aria-hidden />
            </button>
          </Tooltip>
        )}
      </div>
      {loading ? <Skeleton width={96} height={size === 'lg' ? 32 : 24} /> : <div className={clsx(styles.value, 'tabular')}>{value}</div>}
      {(delta != null || comparison != null) && !loading && (
        <div className={styles.footer}>
          {delta != null && (
            <span className={clsx(styles.delta, 'tabular')} data-tone={deltaTone}>
              {delta}
            </span>
          )}
          {comparison != null && <span className={styles.comparison}>{comparison}</span>}
        </div>
      )}
    </div>
  )
}
