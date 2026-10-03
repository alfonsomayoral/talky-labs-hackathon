import type { ComponentPropsWithRef, ReactNode } from 'react'
import { Link, type LinkProps } from 'react-router'
import clsx from 'clsx'
import { LoaderCircle } from 'lucide-react'
import styles from './Button.module.css'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'
export type ButtonSize = 'sm' | 'md'

interface ButtonOwnProps {
  /** `primary` is the orange pill: one per view, for the main action. Default `secondary`. */
  variant?: ButtonVariant
  size?: ButtonSize
  leadingIcon?: ReactNode
  trailingIcon?: ReactNode
}

export interface ButtonProps extends ButtonOwnProps, ComponentPropsWithRef<'button'> {
  /** Shows a spinner, disables the button and sets `aria-busy`. */
  loading?: boolean
}

export function buttonClassName({ variant = 'secondary', size = 'md' }: ButtonOwnProps, className?: string) {
  return clsx(styles.button, styles[variant], styles[size], className)
}

export function Button({
  variant,
  size,
  loading = false,
  leadingIcon,
  trailingIcon,
  className,
  children,
  disabled,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={buttonClassName({ variant, size }, clsx(loading && styles.loading, className))}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <LoaderCircle className={styles.spinner} aria-hidden /> : leadingIcon}
      {children != null && <span className={styles.label}>{children}</span>}
      {trailingIcon}
    </button>
  )
}

export interface ButtonLinkProps extends ButtonOwnProps, LinkProps {}

/** A react-router `Link` styled as a button (navigation, not actions). */
export function ButtonLink({ variant, size, leadingIcon, trailingIcon, className, children, ...rest }: ButtonLinkProps) {
  return (
    <Link className={buttonClassName({ variant, size }, className)} {...rest}>
      {leadingIcon}
      {children != null && <span className={styles.label}>{children as ReactNode}</span>}
      {trailingIcon}
    </Link>
  )
}
