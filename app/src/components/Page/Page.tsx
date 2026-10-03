import type { ReactNode } from 'react'
import clsx from 'clsx'
import styles from './Page.module.css'

export interface PageProps {
  /** Fill the viewport height and let one child (a DataTable) scroll inside instead of the page. */
  fill?: boolean
  /** `narrow` caps the width at 960px for reading-oriented pages. */
  width?: 'full' | 'narrow'
  className?: string
  children: ReactNode
}

/** Route content wrapper: 24px padding, vertical rhythm between blocks. */
export function Page({ fill, width = 'full', className, children }: PageProps) {
  return <div className={clsx(styles.page, fill && styles.fill, width === 'narrow' && styles.narrow, className)}>{children}</div>
}

export interface PageHeaderProps {
  title: ReactNode
  subtitle?: ReactNode
  /** In-page context above the title (the topbar already shows the route breadcrumb). */
  breadcrumb?: ReactNode
  /** Right side: buttons, ViewOptions. One primary action at most. */
  actions?: ReactNode
  /** Row under the title, usually a FilterBar. */
  filters?: ReactNode
  className?: string
}

export function PageHeader({ title, subtitle, breadcrumb, actions, filters, className }: PageHeaderProps) {
  return (
    <header className={clsx(styles.header, className)}>
      {breadcrumb != null && <div className={styles.breadcrumb}>{breadcrumb}</div>}
      <div className={styles.titleRow}>
        <div className={styles.heading}>
          <h1 className={styles.title}>{title}</h1>
          {subtitle != null && <p className={styles.subtitle}>{subtitle}</p>}
        </div>
        {actions != null && <div className={styles.actions}>{actions}</div>}
      </div>
      {filters != null && <div className={styles.filters}>{filters}</div>}
    </header>
  )
}
