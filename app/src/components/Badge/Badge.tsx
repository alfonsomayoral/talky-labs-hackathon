import type { HTMLAttributes, ReactNode } from 'react'
import clsx from 'clsx'
import type { ItemStatus, Priority } from '@/domain/types'
import { ITEM_STATUS, PRIORITY, toneColor, type Tone } from '../status'
import styles from './Badge.module.css'

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: Tone
  /** `soft` (tinted fill) for status, `outline` for quieter metadata. */
  variant?: 'soft' | 'outline'
  /** Leading coloured dot (use with `outline`). */
  dot?: boolean
  icon?: ReactNode
  children: ReactNode
}

/** Small rectangular label for a state or category. */
export function Badge({ tone = 'neutral', variant = 'soft', dot, icon, className, children, ...rest }: BadgeProps) {
  return (
    <span className={clsx(styles.badge, styles[variant], className)} data-tone={tone} {...rest}>
      {dot && <span className={styles.dot} style={{ background: toneColor(tone) }} aria-hidden />}
      {icon}
      <span className={styles.text}>{children}</span>
    </span>
  )
}

/** Item status with the canonical label and colour (AUTO green, NEEDS_HUMAN amber, BLOCKED red, OPEN gray). */
export function StatusBadge({ status, className }: { status: ItemStatus; className?: string }) {
  const meta = ITEM_STATUS[status]
  return (
    <Badge tone={meta.tone} variant="outline" dot className={className}>
      {meta.label}
    </Badge>
  )
}

/** Attention priority (P0 red, P1 amber, P2 blue, P3 gray). */
export function PriorityBadge({ priority, className }: { priority: Priority; className?: string }) {
  const meta = PRIORITY[priority]
  return (
    <Badge tone={meta.tone} className={clsx(styles.priority, className)} title={`Prioridad ${meta.description.toLowerCase()}`}>
      {meta.label}
    </Badge>
  )
}
