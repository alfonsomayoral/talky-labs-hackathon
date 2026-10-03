import type { HTMLAttributes, ReactNode } from 'react'
import clsx from 'clsx'
import { X } from 'lucide-react'
import type { Tone } from '../status'
import styles from './Pill.module.css'

export interface PillProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone
  icon?: ReactNode
  /** Small trailing number (e.g. counts). */
  count?: number
  /** Shows a remove button. */
  onRemove?: () => void
  removeLabel?: string
  children: ReactNode
}

/** Rounded tag for metadata and counts: company code, currency, task, a selected value. */
export function Pill({ tone = 'neutral', icon, count, onRemove, removeLabel = 'Quitar', className, children, ...rest }: PillProps) {
  return (
    <span className={clsx(styles.pill, className)} data-tone={tone} {...rest}>
      {icon}
      <span className={styles.text}>{children}</span>
      {count != null && <span className={clsx(styles.count, 'tabular')}>{count}</span>}
      {onRemove && (
        <button type="button" className={styles.remove} onClick={onRemove} aria-label={removeLabel}>
          <X aria-hidden />
        </button>
      )}
    </span>
  )
}
