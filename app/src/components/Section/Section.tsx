import type { HTMLAttributes, ReactNode } from 'react'
import clsx from 'clsx'
import styles from './Section.module.css'

export interface SectionProps extends Omit<HTMLAttributes<HTMLElement>, 'title'> {
  title: ReactNode
  description?: ReactNode
  /** Small count after the title. */
  count?: number
  actions?: ReactNode
  children: ReactNode
}

/** A titled block within a page (no surface). Stack Sections; put Cards inside when content needs a surface. */
export function Section({ title, description, count, actions, className, children, ...rest }: SectionProps) {
  return (
    <section className={clsx(styles.section, className)} {...rest}>
      <header className={styles.header}>
        <div className={styles.heading}>
          <h2 className={styles.title}>
            {title}
            {count != null && <span className={clsx(styles.count, 'tabular')}>{count}</span>}
          </h2>
          {description != null && <p className={styles.description}>{description}</p>}
        </div>
        {actions != null && <div className={styles.actions}>{actions}</div>}
      </header>
      {children}
    </section>
  )
}
