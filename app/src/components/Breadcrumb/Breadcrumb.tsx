import { Fragment, type ReactNode } from 'react'
import { Link } from 'react-router'
import clsx from 'clsx'
import { ChevronRight } from 'lucide-react'
import styles from './Breadcrumb.module.css'

export interface BreadcrumbItem {
  label: ReactNode
  /** Omit for non-navigable levels (section titles) and the current page. */
  to?: string
}

export interface BreadcrumbProps {
  items: BreadcrumbItem[]
  className?: string
}

/** Path to the current page; the last item is the current page. */
export function Breadcrumb({ items, className }: BreadcrumbProps) {
  return (
    <nav aria-label="Ruta" className={clsx(styles.nav, className)}>
      <ol className={styles.list}>
        {items.map((item, i) => {
          const last = i === items.length - 1
          return (
            <Fragment key={i}>
              <li className={clsx(styles.item, last && styles.current)} aria-current={last ? 'page' : undefined}>
                {item.to && !last ? (
                  <Link to={item.to} className={styles.link}>
                    {item.label}
                  </Link>
                ) : (
                  <span className={styles.text}>{item.label}</span>
                )}
              </li>
              {!last && (
                <li className={styles.separator} aria-hidden>
                  <ChevronRight />
                </li>
              )}
            </Fragment>
          )
        })}
      </ol>
    </nav>
  )
}
