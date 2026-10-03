import type { ComponentPropsWithRef, ReactNode } from 'react'
import clsx from 'clsx'
import { Tooltip } from '../Tooltip/Tooltip'
import type { Side } from '../Popover/floating'
import styles from './IconButton.module.css'

export interface IconButtonProps extends Omit<ComponentPropsWithRef<'button'>, 'children'> {
  icon: ReactNode
  /** Accessible name, also shown as tooltip. */
  label: string
  shortcut?: string[]
  variant?: 'ghost' | 'secondary'
  size?: 'sm' | 'md'
  /** Pressed/selected state (toggle buttons). */
  active?: boolean
  tooltipSide?: Side
  /** Set false when the label is already visible next to it. */
  tooltip?: boolean
}

export function IconButton({
  icon,
  label,
  shortcut,
  variant = 'ghost',
  size = 'md',
  active,
  tooltipSide,
  tooltip = true,
  className,
  type = 'button',
  ...rest
}: IconButtonProps) {
  const button = (
    <button
      type={type}
      aria-label={label}
      aria-pressed={active}
      className={clsx(styles.button, styles[variant], styles[size], active && styles.active, className)}
      {...rest}
    >
      {icon}
    </button>
  )
  if (!tooltip) return button
  return (
    <Tooltip content={label} shortcut={shortcut} side={tooltipSide}>
      {button}
    </Tooltip>
  )
}
