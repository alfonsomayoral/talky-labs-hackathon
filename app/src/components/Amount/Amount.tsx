import clsx from 'clsx'
import { formatMoney } from '@/lib/format'
import styles from './Amount.module.css'

export interface AmountProps {
  /** Integer cents in the company's local currency. null/undefined → «—». */
  cents: number | null | undefined
  /** ISO code: EUR (default), MXN for 3100, USD. */
  currency?: string
  /** Prefix `+` on positive values (deltas, adjustments). */
  signed?: boolean
  /** `1,2 M€`; the exact value goes to the tooltip. */
  compact?: boolean
  decimals?: 0 | 2
  /** JetBrains Mono instead of Inter tabular figures. */
  mono?: boolean
  /** Green positives / red negatives (differences, gaps). */
  colorize?: boolean
  /** Bare number without currency (when the column header carries it). */
  hideCurrency?: boolean
  className?: string
}

/** Money from cents. Always tabular; right-align it in tables. Zero renders muted. */
export function Amount({ cents, currency = 'EUR', signed, compact, decimals, mono, colorize, hideCurrency, className }: AmountProps) {
  const text = formatMoney(cents, currency, {
    signed,
    compact,
    decimals,
    currencyDisplay: hideCurrency ? 'none' : 'symbol',
  })
  const sign = cents == null ? null : Math.sign(cents)
  return (
    <span
      className={clsx(
        styles.amount,
        mono && styles.mono,
        (sign === 0 || sign === null) && styles.muted,
        colorize && sign === 1 && styles.positive,
        colorize && sign === -1 && styles.negative,
        className,
      )}
      title={compact ? formatMoney(cents, currency, { signed }) : undefined}
    >
      {text}
    </span>
  )
}
