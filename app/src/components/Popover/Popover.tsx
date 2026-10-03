import { useCallback, useEffect, useRef, type HTMLAttributes, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import clsx from 'clsx'
import { getFocusable, useLayer } from '@/lib/keyboard'
import { useFloating, type Align, type Side } from './floating'
import { usePresence } from '../usePresence'
import styles from './Popover.module.css'

export interface PopoverProps extends Omit<HTMLAttributes<HTMLDivElement>, 'children'> {
  open: boolean
  onClose: () => void
  /** Element the popover is anchored to (usually its trigger). Focus returns to it on close. */
  anchor: HTMLElement | null
  side?: Side
  align?: Align
  /** Where focus goes on open. Default `first` focusable element. */
  initialFocus?: 'first' | 'container' | 'none'
  children: ReactNode
}

/** Anchored floating surface: closes on outside click and Esc. Building block for Menu, FilterChip, ViewOptions. */
export function Popover({
  open,
  onClose,
  anchor,
  side = 'bottom',
  align = 'start',
  initialFocus = 'first',
  className,
  children,
  ...rest
}: PopoverProps) {
  const presence = usePresence(open)
  const { setFloating, style } = useFloating(anchor, presence.mounted, { side, align })
  const containerRef = useRef<HTMLDivElement | null>(null)
  const setRefs = useCallback(
    (el: HTMLDivElement | null) => {
      containerRef.current = el
      setFloating(el)
    },
    [setFloating],
  )

  useLayer(open, () => {
    onClose()
    anchor?.focus()
  })

  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: PointerEvent) => {
      const target = e.target as Node
      if (containerRef.current?.contains(target) || anchor?.contains(target)) return
      onClose()
    }
    document.addEventListener('pointerdown', onPointerDown, true)
    return () => document.removeEventListener('pointerdown', onPointerDown, true)
  }, [open, anchor, onClose])

  useEffect(() => {
    if (!open || initialFocus === 'none') return
    const el = containerRef.current
    if (!el) return
    const target = initialFocus === 'first' ? (getFocusable(el)[0] ?? el) : el
    target.focus({ preventScroll: true })
  }, [open, initialFocus])

  if (!presence.mounted) return null
  return createPortal(
    <div
      ref={setRefs}
      tabIndex={-1}
      className={clsx(styles.popover, presence.closing && styles.closing, className)}
      inert={presence.closing}
      aria-hidden={presence.closing || undefined}
      style={style}
      {...rest}
    >
      {children}
    </div>,
    document.body,
  )
}
