import type { HTMLAttributes } from 'react'
import clsx from 'clsx'
import styles from './Kbd.module.css'

export interface KbdProps extends HTMLAttributes<HTMLElement> {
  /** One key per Kbd; render several side by side for sequences (`G` `R`). */
  children: string
}

export function Kbd({ className, children, ...rest }: KbdProps) {
  return (
    <kbd className={clsx(styles.kbd, className)} {...rest}>
      {children}
    </kbd>
  )
}
