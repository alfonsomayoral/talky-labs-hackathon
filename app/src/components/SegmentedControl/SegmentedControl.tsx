import { useRef, type KeyboardEvent, type ReactNode } from 'react'
import clsx from 'clsx'
import styles from './SegmentedControl.module.css'

export interface SegmentedOption<V extends string> {
  value: V
  label: ReactNode
  icon?: ReactNode
}

export interface SegmentedControlProps<V extends string> {
  options: SegmentedOption<V>[]
  value: V
  onChange: (value: V) => void
  size?: 'sm' | 'md'
  'aria-label': string
  className?: string
}

/** Exclusive choice among 2–4 views of the same data (e.g. Lista / Mosaico, EUR / MXN). */
export function SegmentedControl<V extends string>({ options, value, onChange, size = 'md', className, ...aria }: SegmentedControlProps<V>) {
  const ref = useRef<HTMLDivElement>(null)

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = options.findIndex((o) => o.value === value)
    const delta = e.key === 'ArrowRight' || e.key === 'ArrowDown' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowUp' ? -1 : 0
    if (!delta) return
    e.preventDefault()
    const next = (i + delta + options.length) % options.length
    onChange(options[next].value)
    ref.current?.querySelectorAll<HTMLElement>('[role="radio"]')[next]?.focus()
  }

  return (
    <div ref={ref} role="radiogroup" className={clsx(styles.group, styles[size], className)} onKeyDown={onKeyDown} {...aria}>
      {options.map((o) => {
        const checked = o.value === value
        return (
          <button
            key={o.value}
            type="button"
            role="radio"
            aria-checked={checked}
            tabIndex={checked ? 0 : -1}
            className={clsx(styles.option, checked && styles.checked)}
            onClick={() => onChange(o.value)}
          >
            {o.icon}
            {o.label}
          </button>
        )
      })}
    </div>
  )
}
