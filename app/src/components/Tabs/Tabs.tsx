import { useId, useRef, type KeyboardEvent, type ReactNode } from 'react'
import clsx from 'clsx'
import styles from './Tabs.module.css'

export interface TabItem {
  id: string
  label: ReactNode
  count?: number
  disabled?: boolean
}

export interface TabsProps {
  tabs: TabItem[]
  value: string
  onChange: (id: string) => void
  /** Links tabs to their TabPanel (`<TabPanel idPrefix={…} id={…}>`). Defaults to an auto id. */
  idPrefix?: string
  'aria-label'?: string
  className?: string
}

const tabId = (prefix: string, id: string) => `${prefix}-tab-${id}`
const panelId = (prefix: string, id: string) => `${prefix}-panel-${id}`

/** Underlined tabs (←/→, Home/End). Render the active content yourself, ideally inside TabPanel. */
export function Tabs({ tabs, value, onChange, idPrefix, className, ...aria }: TabsProps) {
  const autoId = useId()
  const prefix = idPrefix ?? autoId
  const listRef = useRef<HTMLDivElement>(null)

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const enabled = tabs.filter((t) => !t.disabled)
    const i = enabled.findIndex((t) => t.id === value)
    let next: TabItem | undefined
    if (e.key === 'ArrowRight') next = enabled[(i + 1) % enabled.length]
    else if (e.key === 'ArrowLeft') next = enabled[(i - 1 + enabled.length) % enabled.length]
    else if (e.key === 'Home') next = enabled[0]
    else if (e.key === 'End') next = enabled[enabled.length - 1]
    if (!next) return
    e.preventDefault()
    onChange(next.id)
    listRef.current?.querySelector<HTMLElement>(`#${CSS.escape(tabId(prefix, next.id))}`)?.focus()
  }

  return (
    <div ref={listRef} role="tablist" className={clsx(styles.list, className)} onKeyDown={onKeyDown} {...aria}>
      {tabs.map((t) => {
        const selected = t.id === value
        return (
          <button
            key={t.id}
            id={tabId(prefix, t.id)}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={panelId(prefix, t.id)}
            tabIndex={selected ? 0 : -1}
            disabled={t.disabled}
            className={clsx(styles.tab, selected && styles.selected)}
            onClick={() => onChange(t.id)}
          >
            {t.label}
            {t.count != null && <span className={clsx(styles.count, 'tabular')}>{t.count}</span>}
          </button>
        )
      })}
    </div>
  )
}

export function TabPanel({ idPrefix, id, className, children }: { idPrefix: string; id: string; className?: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={panelId(idPrefix, id)} aria-labelledby={tabId(idPrefix, id)} className={className}>
      {children}
    </div>
  )
}
