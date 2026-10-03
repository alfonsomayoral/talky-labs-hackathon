import type { ReactNode } from 'react'
import clsx from 'clsx'
import styles from './KeyValue.module.css'

export interface KeyValueItem {
  label: ReactNode
  value: ReactNode
  /** Render the value in JetBrains Mono (ids, accounts, IBAN). */
  mono?: boolean
}

export interface KeyValueProps {
  items: KeyValueItem[]
  /** Pairs per row. Default 1. */
  columns?: 1 | 2
  /** Label column width in px. Default 140. */
  labelWidth?: number
  className?: string
}

/** Definition list for record details (panel summaries, master data). */
export function KeyValue({ items, columns = 1, labelWidth = 140, className }: KeyValueProps) {
  return (
    <dl
      className={clsx(styles.list, columns === 2 && styles.two, className)}
      style={{ ['--kv-label' as string]: `${labelWidth}px` }}
    >
      {items.map((item, i) => (
        <div key={i} className={styles.row}>
          <dt className={styles.label}>{item.label}</dt>
          <dd className={clsx(styles.value, item.mono && styles.mono)}>{item.value ?? '—'}</dd>
        </div>
      ))}
    </dl>
  )
}
