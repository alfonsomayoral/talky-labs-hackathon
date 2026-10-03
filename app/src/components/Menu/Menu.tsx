import { cloneElement, useRef, useState, type KeyboardEvent, type MouseEvent, type ReactElement, type ReactNode, type Ref } from 'react'
import clsx from 'clsx'
import { Check } from 'lucide-react'
import { Popover } from '../Popover/Popover'
import type { Align, Side } from '../Popover/floating'
import styles from './Menu.module.css'

export type MenuItem =
  | {
      type?: 'item'
      id: string
      label: ReactNode
      icon?: ReactNode
      /** Right-aligned secondary text or shortcut. */
      hint?: ReactNode
      /** Second line under the label. */
      description?: ReactNode
      /** Renders a check mark column (single/multi choice menus). */
      checked?: boolean
      disabled?: boolean
      danger?: boolean
      onSelect: () => void
    }
  | { type: 'separator'; id: string }
  | { type: 'label'; id: string; label: ReactNode }

interface TriggerProps {
  onClick?: (e: MouseEvent<HTMLElement>) => void
  onKeyDown?: (e: KeyboardEvent<HTMLElement>) => void
  'aria-haspopup'?: 'menu'
  'aria-expanded'?: boolean
  ref?: Ref<HTMLElement>
}

export interface MenuProps {
  /** The button that opens the menu (Button, IconButton…). It receives click/keyboard handlers. */
  trigger: ReactElement<TriggerProps>
  items: MenuItem[]
  side?: Side
  align?: Align
  'aria-label'?: string
  /** Class for the floating list (e.g. a fixed width). */
  className?: string
}

/** Dropdown of actions or choices. ↑/↓ to move, Enter to pick, Esc to close, typing jumps by first letter. */
export function Menu({ trigger, items, side = 'bottom', align = 'start', className, ...aria }: MenuProps) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null)
  const [open, setOpen] = useState(false)
  const listRef = useRef<HTMLDivElement>(null)
  const hasChecks = items.some((i) => (i.type ?? 'item') === 'item' && 'checked' in i && i.checked !== undefined)

  const close = () => setOpen(false)
  const p = trigger.props

  const triggerEl = cloneElement(trigger, {
    onClick: (e: MouseEvent<HTMLElement>) => {
      p.onClick?.(e)
      setAnchor(e.currentTarget)
      setOpen((o) => !o)
    },
    onKeyDown: (e: KeyboardEvent<HTMLElement>) => {
      p.onKeyDown?.(e)
      if (e.key === 'ArrowDown' && !open) {
        e.preventDefault()
        setAnchor(e.currentTarget)
        setOpen(true)
      }
    },
    'aria-haspopup': 'menu',
    'aria-expanded': open,
  })

  const focusables = () => Array.from(listRef.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]:not(:disabled)') ?? [])

  const onListKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const els = focusables()
    const i = els.indexOf(document.activeElement as HTMLElement)
    let next: HTMLElement | undefined
    if (e.key === 'ArrowDown') next = els[(i + 1) % els.length]
    else if (e.key === 'ArrowUp') next = els[(i - 1 + els.length) % els.length]
    else if (e.key === 'Home') next = els[0]
    else if (e.key === 'End') next = els[els.length - 1]
    else if (e.key === 'Tab') {
      e.preventDefault()
      close()
      return
    } else if (e.key.length === 1 && /\S/.test(e.key)) {
      const key = e.key.toLowerCase()
      const ordered = [...els.slice(i + 1), ...els.slice(0, i + 1)]
      next = ordered.find((el) => el.textContent?.trim().toLowerCase().startsWith(key))
    }
    if (next) {
      e.preventDefault()
      next.focus()
    }
  }

  return (
    <>
      {triggerEl}
      <Popover open={open} onClose={close} anchor={anchor} side={side} align={align} className={className}>
        <div ref={listRef} role="menu" className={styles.menu} onKeyDown={onListKeyDown} {...aria}>
          {items.map((item) => {
            if (item.type === 'separator') return <div key={item.id} role="separator" className={styles.separator} />
            if (item.type === 'label')
              return (
                <div key={item.id} className={styles.groupLabel}>
                  {item.label}
                </div>
              )
            const checkable = hasChecks && item.checked !== undefined
            return (
              <button
                key={item.id}
                type="button"
                role={checkable ? 'menuitemcheckbox' : 'menuitem'}
                aria-checked={checkable ? item.checked : undefined}
                disabled={item.disabled}
                tabIndex={-1}
                className={clsx(styles.item, item.danger && styles.danger)}
                onClick={() => {
                  close()
                  anchor?.focus()
                  item.onSelect()
                }}
                onPointerMove={(e) => e.currentTarget.focus()}
              >
                {hasChecks && <span className={styles.check}>{item.checked && <Check aria-hidden />}</span>}
                {item.icon && <span className={styles.icon}>{item.icon}</span>}
                <span className={styles.text}>
                  <span className={styles.label}>{item.label}</span>
                  {item.description != null && <span className={styles.description}>{item.description}</span>}
                </span>
                {item.hint != null && <span className={styles.hint}>{item.hint}</span>}
              </button>
            )
          })}
        </div>
      </Popover>
    </>
  )
}
