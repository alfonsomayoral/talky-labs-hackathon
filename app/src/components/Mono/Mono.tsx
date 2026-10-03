import type { HTMLAttributes, ReactNode } from 'react'
import clsx from 'clsx'
import styles from './Mono.module.css'

export interface MonoProps extends HTMLAttributes<HTMLSpanElement> {
  /** Secondary ids (e.g. a line number next to the entry id). */
  muted?: boolean
  children: ReactNode
}

/** Identifiers, accounts and codes: API004128, 40090000, BL0000085, §2.2.3. */
export function Mono({ muted, className, children, ...rest }: MonoProps) {
  return (
    <span className={clsx(styles.mono, muted && styles.muted, className)} {...rest}>
      {children}
    </span>
  )
}
