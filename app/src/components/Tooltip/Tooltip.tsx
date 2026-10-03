import {
  cloneElement,
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type PointerEvent,
  type ReactElement,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { useFloating, type Side } from '../Popover/floating'
import styles from './Tooltip.module.css'

interface TriggerProps {
  onPointerEnter?: (e: PointerEvent<HTMLElement>) => void
  onPointerLeave?: (e: PointerEvent<HTMLElement>) => void
  onPointerDown?: (e: PointerEvent<HTMLElement>) => void
  onFocus?: (e: FocusEvent<HTMLElement>) => void
  onBlur?: (e: FocusEvent<HTMLElement>) => void
  'aria-describedby'?: string
}

export interface TooltipProps {
  content: ReactNode
  /** Keys shown after the text, e.g. `['G', 'R']`. */
  shortcut?: string[]
  side?: Side
  /** Hover delay in ms. Keyboard focus shows it at once. */
  delay?: number
  /** A single element that accepts pointer/focus handlers (Button, IconButton, a, span…). */
  children: ReactElement<TriggerProps>
}

/** Short label on hover/focus. Supplementary only: never the sole carrier of information. */
export function Tooltip({ content, shortcut, side = 'top', delay = 450, children }: TooltipProps) {
  const id = useId()
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined)
  const open = anchor !== null
  const { setFloating, style } = useFloating(anchor, open, { side, align: 'center', offset: 6 })

  useEffect(() => () => clearTimeout(timer.current), [])

  const hide = () => {
    clearTimeout(timer.current)
    setAnchor(null)
  }
  const p = children.props

  const trigger = cloneElement(children, {
    onPointerEnter: (e: PointerEvent<HTMLElement>) => {
      p.onPointerEnter?.(e)
      if (e.pointerType === 'touch') return
      const target = e.currentTarget
      clearTimeout(timer.current)
      timer.current = setTimeout(() => setAnchor(target), delay)
    },
    onPointerLeave: (e: PointerEvent<HTMLElement>) => {
      p.onPointerLeave?.(e)
      hide()
    },
    onPointerDown: (e: PointerEvent<HTMLElement>) => {
      p.onPointerDown?.(e)
      hide()
    },
    onFocus: (e: FocusEvent<HTMLElement>) => {
      p.onFocus?.(e)
      if (e.currentTarget.matches(':focus-visible')) setAnchor(e.currentTarget)
    },
    onBlur: (e: FocusEvent<HTMLElement>) => {
      p.onBlur?.(e)
      hide()
    },
    'aria-describedby': open ? id : p['aria-describedby'],
  })

  return (
    <>
      {trigger}
      {open &&
        createPortal(
          <div ref={setFloating} id={id} role="tooltip" className={styles.tooltip} style={style}>
            <span>{content}</span>
            {shortcut && shortcut.length > 0 && (
              <span className={styles.keys}>
                {shortcut.map((k) => (
                  <kbd key={k} className={styles.key}>
                    {k}
                  </kbd>
                ))}
              </span>
            )}
          </div>,
          document.body,
        )}
    </>
  )
}
