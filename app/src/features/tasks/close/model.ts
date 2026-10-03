// Pure helpers behind /tareas/cierre: rows per item, vendor history for accruals, prepaid calendar, FX breakdown and debt aging.

import type { ApInvoice, ArInvoice, Cents, CloseRow, OpenItem, WorkItem } from '@/domain/types'

const KEY_FIELD: Record<string, keyof CloseRow> = {
  ACCRUAL: 'vendor',
  PREPAID: 'invoice',
  FX_REVAL: 'item',
  BAD_DEBT: 'customer',
  WIP_REVENUE: 'billing_item',
  DOUBTFUL_RECLASS: 'customer',
}

/** Delivered rows behind a close item (`close:<type>/<company>/<key>`); ACCRUAL keys may group several. */
export function closeRowsOf(rows: readonly CloseRow[], item: Pick<WorkItem, 'key'>): CloseRow[] {
  const [type, company, ...rest] = item.key.split('/')
  const key = rest.join('/')
  const field = KEY_FIELD[type] ?? 'customer'
  return rows.filter((r) => String(r.type) === type && String(r.company) === company && String(r[field] ?? '-') === key)
}

export const closeKeyValue = (item: Pick<WorkItem, 'key'>) => item.key.split('/').slice(2).join('/')

export const monthEndOf = (month: string) => {
  const [y, m] = month.split('-').map(Number)
  return new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10)
}

// ---------------------------------------------------------------- accruals

export interface VendorHistory {
  /** YYYY-MM of the months before the close, oldest first. */
  months: string[]
  /** Σ net of the vendor's invoices issued in each month (cents, invoice currency). */
  values: Cents[]
  /** Mean over the months that had an invoice (null without any). */
  average: Cents | null
}

/** Invoices of a vendor to a company issued in the `months` months up to the close. */
export function vendorHistory(invoices: readonly ApInvoice[], vendor: string, company: string, month: string, months = 12): VendorHistory {
  const [y, m] = month.split('-').map(Number)
  const list = Array.from({ length: months }, (_, i) => {
    const d = new Date(Date.UTC(y, m - months + i, 1))
    return d.toISOString().slice(0, 7)
  })
  const index = new Map(list.map((x, i) => [x, i]))
  const values = list.map(() => 0)
  const seen = list.map(() => false)
  for (const inv of invoices) {
    if (inv.vendor !== vendor || inv.company !== company || inv.kind === 'credit_note') continue
    const i = index.get(inv.issue_date.slice(0, 7))
    if (i === undefined) continue
    values[i] += inv.net
    seen[i] = true
  }
  const n = seen.filter(Boolean).length
  return { months: list, values, average: n ? Math.round(values.reduce((s, x) => s + x, 0) / n) : null }
}

// ---------------------------------------------------------------- prepaid

/** `(k/n)` of a prepaid entry header: month k of n of the coverage. */
export function prepaidFraction(text: string | null | undefined): { k: number; n: number } | null {
  const m = text?.match(/\((\d+)\/(\d+)\)/)
  if (!m) return null
  const k = Number(m[1])
  const n = Number(m[2])
  return n > 0 && k >= 1 && k <= n ? { k, n } : null
}

// ---------------------------------------------------------------- FX revaluation

export interface FxBreakdown {
  currency: string
  /** Open amount in the item currency (cents). */
  foreign: Cents
  /** Local units per unit of `currency` at the month-end SYN-BCE rate. */
  rate: number
  /** foreign × rate, in local cents. */
  value: Cents
  /** Book value before the revaluation: value − amount. */
  book: Cents
}

/** «valor a tipo de cierre − valor contable» from the row's `foreign` and `rate` (null when the row does not carry them). */
export function fxBreakdown(row: Partial<CloseRow> & { foreign?: unknown; rate?: unknown; currency?: unknown }): FxBreakdown | null {
  const foreign = typeof row.foreign === 'number' ? row.foreign : null
  const rate = typeof row.rate === 'number' ? row.rate : null
  if (foreign === null || rate === null || typeof row.amount !== 'number') return null
  const value = Math.round(foreign * rate)
  return { currency: typeof row.currency === 'string' ? row.currency : '', foreign, rate, value, book: value - row.amount }
}

/** What the FX item points to: an AP invoice, a GL account or a bank account. */
export function fxTarget(item: string): { kind: 'ap' | 'gl' | 'bank' | 'other'; id: string } {
  const [prefix, ...rest] = item.split(':')
  const id = rest.join(':')
  if (prefix === 'AP') return { kind: 'ap', id }
  if (prefix === 'GL') return { kind: 'gl', id }
  if (prefix === 'BANK') return { kind: 'bank', id }
  return { kind: 'other', id: item }
}

// ---------------------------------------------------------------- bad debt aging

export type AgingBucket = 'current' | 'over180' | 'over365'

export const AGING_LABEL: Record<AgingBucket, string> = {
  current: 'Hasta 180 días',
  over180: '181–365 días (50 %)',
  over365: 'Más de 365 días (100 %)',
}

export interface AgingLine {
  invoice: string
  due: string | null
  days: number | null
  balance: Cents
  bucket: AgingBucket
  required: Cents
}

export interface Aging {
  lines: AgingLine[]
  totals: Record<AgingBucket, Cents>
  /** Provision the policy asks for: 50 % (floor) over 180 days, 100 % over 365; 100 % of everything when insolvent. */
  required: Cents
}

const DAY = 86_400_000
const INSOLVENCY_ACCOUNTS = new Set(['43600000', '43000900'])

/**
 * Open receivables of a customer by days past due at the close (strict > 180 and > 365): 43000000, and when
 * the customer is insolvent also doubtful debts (43600000) and retained guarantees (43000900), all at 100 %.
 */
export function agingOf(openItems: readonly OpenItem[], invoices: readonly ArInvoice[], customer: string, company: string, monthEnd: string, insolvent: boolean): Aging {
  const due = new Map(invoices.filter((i) => i.customer === customer).map((i) => [i.id, i.due_date]))
  const end = Date.parse(monthEnd)
  const lines = openItems
    .filter((o) => o.partner === customer && o.company === company && (o.account === '43000000' || (insolvent && INSOLVENCY_ACCOUNTS.has(o.account))) && o.balance > 0)
    .map((o): AgingLine => {
      const d = due.get(o.assignment) ?? null
      const days = d ? Math.round((end - Date.parse(d)) / DAY) : null
      const bucket: AgingBucket = days !== null && days > 365 ? 'over365' : days !== null && days > 180 ? 'over180' : 'current'
      const required = insolvent || bucket === 'over365' ? o.balance : bucket === 'over180' ? Math.floor(o.balance / 2) : 0
      return { invoice: o.assignment, due: d, days, balance: o.balance, bucket, required }
    })
    .sort((a, b) => (b.days ?? -1) - (a.days ?? -1))
  const totals: Record<AgingBucket, Cents> = { current: 0, over180: 0, over365: 0 }
  for (const l of lines) totals[l.bucket] += l.balance
  return { lines, totals, required: lines.reduce((s, l) => s + l.required, 0) }
}
