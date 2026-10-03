import clsx from 'clsx'
import type { ItemStatus } from '@/domain/types'
import { ITEM_STATUS, toneColor, type Tone } from '../status'
import styles from './StatusDot.module.css'

export interface StatusDotProps {
  /** Either a tone or an item status (mapped through ITEM_STATUS). */
  tone?: Tone
  status?: ItemStatus
  /** Accessible label; defaults to the status label. Omit for purely decorative dots next to text. */
  label?: string
  /** Soft halo animation for "in progress". */
  pulse?: boolean
  className?: string
}

export function StatusDot({ tone, status, label, pulse, className }: StatusDotProps) {
  const meta = status ? ITEM_STATUS[status] : null
  const t = tone ?? meta?.tone ?? 'neutral'
  const name = label ?? meta?.label
  return (
    <span
      className={clsx(styles.dot, pulse && styles.pulse, className)}
      style={{ ['--dot-color' as string]: toneColor(t) }}
      role={name ? 'img' : undefined}
      aria-label={name}
      aria-hidden={name ? undefined : true}
      title={name}
    />
  )
}
