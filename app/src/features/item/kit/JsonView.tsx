import { useState } from 'react'
import clsx from 'clsx'
import { ChevronRight } from 'lucide-react'
import { Amount, Mono } from '@/components'
import styles from './JsonView.module.css'

export interface JsonViewProps {
  value: unknown
  /** Levels expanded at first. */
  depth?: number
  className?: string
}

// Integer fields holding cents in ERP records and deliverables.
const MONEY_KEYS = /^(amount|net|tax|gross|payable|withholding|retention|balance|principal|debit|credit|advance|interest|fee|total|value|cumulative|previous|current|unit_price|target|monthly_eur_\d+|old_fee|new_fee|deviations|budget_cost)$/

/** Compact, collapsible view of a JSON record; money-like integer fields are shown as amounts. */
export function JsonView({ value, depth = 1, className }: JsonViewProps) {
  return (
    <div className={clsx(styles.json, className)}>
      <Node value={value} depth={depth} currency={currencyOf(value)} />
    </div>
  )
}

const currencyOf = (v: unknown): string => {
  const c = v && typeof v === 'object' && !Array.isArray(v) ? (v as Record<string, unknown>).currency : null
  return typeof c === 'string' && /^[A-Z]{3}$/.test(c) ? c : 'EUR'
}

function Scalar({ name, value, currency }: { name?: string; value: unknown; currency: string }) {
  if (value === null || value === undefined) return <span className={styles.null}>—</span>
  if (typeof value === 'boolean') return <span className={styles.bool}>{value ? 'sí' : 'no'}</span>
  if (typeof value === 'number') {
    if (name && MONEY_KEYS.test(name) && Number.isInteger(value)) {
      return (
        <span className={styles.money}>
          <Amount cents={value} currency={currency} />
          <Mono muted>{value}</Mono>
        </span>
      )
    }
    return <Mono>{value}</Mono>
  }
  const s = String(value)
  return /^[A-Z0-9][A-Z0-9_\-#/.:]{2,}$/i.test(s) && !s.includes(' ') ? <Mono>{s}</Mono> : <span className={styles.string}>{s}</span>
}

function Node({ value, depth, currency }: { value: unknown; depth: number; currency: string }) {
  if (Array.isArray(value)) {
    if (!value.length) return <span className={styles.null}>[]</span>
    if (value.every((v) => v === null || typeof v !== 'object')) {
      return (
        <span className={styles.inline}>
          {value.map((v, i) => (
            <span key={i}>
              <Scalar value={v} currency={currency} />
              {i < value.length - 1 ? ', ' : ''}
            </span>
          ))}
        </span>
      )
    }
    return (
      <ol className={styles.list}>
        {value.map((v, i) => (
          <li key={i}>
            <Entry name={`${i + 1}`} value={v} depth={depth} currency={currencyOf(v) || currency} />
          </li>
        ))}
      </ol>
    )
  }
  if (value && typeof value === 'object') {
    const entries = Object.entries(value as Record<string, unknown>)
    if (!entries.length) return <span className={styles.null}>{'{}'}</span>
    return (
      <dl className={styles.object}>
        {entries.map(([k, v]) => (
          <Entry key={k} name={k} value={v} depth={depth} currency={currency} />
        ))}
      </dl>
    )
  }
  return <Scalar value={value} currency={currency} />
}

function Entry({ name, value, depth, currency }: { name: string; value: unknown; depth: number; currency: string }) {
  const nested = value !== null && typeof value === 'object' && !(Array.isArray(value) && value.every((v) => v === null || typeof v !== 'object'))
  const [open, setOpen] = useState(depth > 0)
  if (!nested) {
    return (
      <div className={styles.row}>
        <dt className={styles.key}>{name}</dt>
        <dd className={styles.value}>
          <Scalar name={name} value={value} currency={currency} />
        </dd>
      </div>
    )
  }
  const size = Array.isArray(value) ? value.length : Object.keys(value as object).length
  return (
    <div className={styles.nested}>
      <button type="button" className={styles.toggle} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <ChevronRight aria-hidden className={clsx(styles.chevron, open && styles.open)} />
        <span className={styles.key}>{name}</span>
        <span className={styles.size}>{Array.isArray(value) ? `[${size}]` : `{${size}}`}</span>
      </button>
      {open && (
        <div className={styles.children}>
          <Node value={value} depth={depth - 1} currency={currency} />
        </div>
      )}
    </div>
  )
}
