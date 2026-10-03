import type { HTMLAttributes, ReactNode } from 'react'
import clsx from 'clsx'
import styles from './Card.module.css'

export interface CardProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  title?: ReactNode
  /** Secondary line under the title. */
  description?: ReactNode
  /** Right side of the header (a Button, a Menu, a link). */
  actions?: ReactNode
  /** `none` for edge-to-edge content (tables, lists). Default `md` (16px). */
  padding?: 'none' | 'sm' | 'md'
  /** Hover affordance for clickable cards. */
  interactive?: boolean
  children?: ReactNode
}

/** White surface with a hairline border. No heavy shadows. */
export function Card({ title, description, actions, padding = 'md', interactive, className, children, ...rest }: CardProps) {
  const hasHeader = title != null || actions != null
  return (
    <section className={clsx(styles.card, interactive && styles.interactive, className)} {...rest}>
      {hasHeader && (
        <header className={styles.header}>
          <div className={styles.heading}>
            {title != null && <h3 className={styles.title}>{title}</h3>}
            {description != null && <p className={styles.description}>{description}</p>}
          </div>
          {actions != null && <div className={styles.actions}>{actions}</div>}
        </header>
      )}
      {children != null && <div className={clsx(styles.body, styles[`pad-${padding}`])}>{children}</div>}
    </section>
  )
}
