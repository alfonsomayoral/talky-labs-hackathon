import type { ReactNode } from 'react'
import clsx from 'clsx'
import styles from './EmptyState.module.css'

export interface EmptyStateProps {
  /** A lucide icon element. No illustrations. */
  icon?: ReactNode
  title: ReactNode
  description?: ReactNode
  /** Usually one Button/ButtonLink that resolves the emptiness. */
  action?: ReactNode
  /** `sm` for inside cards and tables. */
  size?: 'sm' | 'md'
  className?: string
}

export function EmptyState({ icon, title, description, action, size = 'md', className }: EmptyStateProps) {
  return (
    <div className={clsx(styles.empty, styles[size], className)}>
      {icon && (
        <div className={styles.icon} aria-hidden>
          {icon}
        </div>
      )}
      <div className={styles.text}>
        <p className={styles.title}>{title}</p>
        {description != null && <p className={styles.description}>{description}</p>}
      </div>
      {action != null && <div className={styles.action}>{action}</div>}
    </div>
  )
}
