// Aplicación de cobros: where each receipt goes (sources = uses of its adjustment), how much of 55500000
// is emptied per company, and the customer's open items before and after each receipt.

import type { ArCashRow, ArResidualType, DatasetCore, JeLine, JournalEntryOut, WorkItem } from '@/domain/types'
import { AR_RESIDUAL_CATALOG } from '@/domain/catalog/policy'
import type { Tone } from '@/components'

const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)
const list = <T>(v: T[] | null | undefined): T[] => (Array.isArray(v) ? v : [])

export const SUSPENSE = '55500000'

/** Differences that cover part of the invoices instead of cash (they debit an account in the adjustment). */
const DEDUCTION_TYPES: ReadonlySet<string> = new Set<ArResidualType>(['PENALTY', 'NETTING_AP'])

export interface Flow {
  key: string
  label: string
  /** Invoice, promissory note or document the flow refers to. */
  ref: string | null
  amount: number
  tone: Tone
}

export interface Allocation {
  cash: number
  /** What pays: the receipt itself plus the differences that stand in for cash (penalty, netting). */
  sources: Flow[]
  /** What is settled: invoices, promissory notes and the differences credited elsewhere. */
  uses: Flow[]
  /** Σsources − Σuses before the balancing flow; ≠ 0 means part of the receipt is left unexplained. */
  unexplained: number
}

const residualLabel = (type: string) => AR_RESIDUAL_CATALOG[type as ArResidualType]?.label ?? type

/**
 * Splits a receipt into sources and uses. Σsources = Σuses always holds: an unexplained remainder
 * becomes a «queda en 55500000» use (or an uncovered source when the row settles more than it receives).
 */
export function allocation(row: ArCashRow, cash: number): Allocation {
  const sources: Flow[] = [{ key: 'cash', label: 'Abono en 55500000', ref: null, amount: cash, tone: 'info' }]
  const uses: Flow[] = []
  list(row.applications).forEach((a, i) => {
    const pagare = str(a.pagare)
    uses.push({
      key: `app-${i}`,
      label: pagare ? `Pagaré ${pagare}` : `Factura ${str(a.invoice) ?? '—'}`,
      ref: pagare ? `PAG${pagare}` : str(a.invoice),
      amount: num(a.amount),
      tone: pagare ? 'info' : 'ok',
    })
  })
  list(row.residuals).forEach((r, i) => {
    const type = String(r.type)
    const flow: Flow = { key: `res-${i}`, label: residualLabel(type), ref: str(r.invoice), amount: num(r.amount), tone: 'warn' }
    if (DEDUCTION_TYPES.has(type)) sources.push(flow)
    else uses.push(flow)
  })
  const sum = (xs: Flow[]) => xs.reduce((s, f) => s + f.amount, 0)
  const unexplained = sum(sources) - sum(uses)
  if (unexplained > 0) uses.push({ key: 'left', label: 'Queda en 55500000', ref: null, amount: unexplained, tone: 'danger' })
  if (unexplained < 0) sources.push({ key: 'uncovered', label: 'Sin cubrir', ref: null, amount: -unexplained, tone: 'danger' })
  return { cash, sources, uses, unexplained }
}

const companyOf = (line: JeLine, item: WorkItem): string => str(line.company) ?? item.company ?? '—'

export interface SuspenseClearing {
  company: string
  currency: string
  receipts: number
  /** Σ receipt amounts (bank line, local currency). */
  received: number
  /** Net debit of 55500000 in the adjustments. */
  cleared: number
  /** What stays in 55500000 after cash application. */
  remaining: number
}

/** Per company: what the bank put in 55500000 (N43AUTO) and what the adjustments take out of it. */
export function suspenseClearing(items: readonly WorkItem[], rows: readonly ArCashRow[], core: Pick<DatasetCore, 'companies'>): SuspenseClearing[] {
  const by = new Map<string, SuspenseClearing>()
  const at = (company: string) => {
    let c = by.get(company)
    if (!c) {
      const currency = core.companies.find((x) => x.code === company)?.currency ?? 'EUR'
      c = { company, currency, receipts: 0, received: 0, cleared: 0, remaining: 0 }
      by.set(company, c)
    }
    return c
  }
  for (const it of items) {
    if (it.task !== 'ar_cash') continue
    const c = at(it.company ?? '—')
    c.receipts++
    c.received += num(it.amount)
    for (const l of list(rows[it.rowIndex]?.adjustment)) {
      if (l.account === SUSPENSE) at(companyOf(l, it)).cleared += num(l.debit) - num(l.credit)
    }
  }
  return [...by.values()].map((c) => ({ ...c, remaining: c.received - c.cleared })).sort((a, b) => a.company.localeCompare(b.company))
}

/** Customer accounts shown in the open-item view: invoices, promissory notes and advances / amounts to refund. */
export const CUSTOMER_ACCOUNTS: readonly string[] = ['43000000', '43100000', '43800000']

export interface OpenLine {
  account: string
  assignment: string | null
  before: number
  after: number
  /** Changed by this receipt. */
  touched: boolean
}

type Balances = Map<string, number>
const balanceKey = (company: string, account: string, partner: string, assignment: string | null) => `${company}|${account}|${partner}|${assignment ?? ''}`

function post(b: Balances, company: string, lines: readonly JeLine[]) {
  for (const l of lines) {
    const partner = str(l.partner)
    if (!partner || !CUSTOMER_ACCOUNTS.includes(l.account)) continue
    const k = balanceKey(str(l.company) ?? company, l.account, partner, str(l.assignment))
    b.set(k, (b.get(k) ?? 0) + num(l.debit) - num(l.credit))
  }
}

const receiptOrder = (a: WorkItem, b: WorkItem) => (a.date ?? '').localeCompare(b.date ?? '') || a.key.localeCompare(b.key)

/**
 * Open items of the receipt's customer in its company, before and after the receipt. «Before» starts
 * from erp/open_items.jsonl plus the month's invoices posted by then (ar_billing entries) and applies the earlier
 * receipts of the month in date order, so a duplicate payment finds its invoice already settled.
 */
export function customerOpenItems(
  target: WorkItem,
  items: readonly WorkItem[],
  cashRows: readonly ArCashRow[],
  billingEntries: readonly JournalEntryOut[],
  core: Pick<DatasetCore, 'openItems'>,
): OpenLine[] {
  const row = cashRows[target.rowIndex]
  const customer = str(row?.customer)
  const company = target.company
  if (!customer || !company) return []
  const b: Balances = new Map()
  for (const o of core.openItems) {
    if (o.partner === customer && CUSTOMER_ACCOUNTS.includes(o.account)) {
      const k = balanceKey(o.company, o.account, o.partner, str(o.assignment))
      b.set(k, (b.get(k) ?? 0) + num(o.balance))
    }
  }
  for (const e of billingEntries) {
    const posted = str(e.posting_date)
    if (!posted || !target.date || posted <= target.date) post(b, e.company, list(e.lines))
  }
  const receipts = items.filter((it) => it.task === 'ar_cash' && receiptOrder(it, target) < 0)
  for (const it of receipts.sort(receiptOrder)) post(b, it.company ?? '', list(cashRows[it.rowIndex]?.adjustment))
  const before = new Map(b)
  post(b, company, list(row.adjustment))

  const out: OpenLine[] = []
  for (const k of new Set([...before.keys(), ...b.keys()])) {
    const [c, account, partner, assignment] = k.split('|')
    if (c !== company || partner !== customer) continue
    const was = before.get(k) ?? 0
    const now = b.get(k) ?? 0
    if (was === 0 && now === 0) continue
    out.push({ account, assignment: assignment || null, before: was, after: now, touched: was !== now })
  }
  return out.sort((x, y) => Number(y.touched) - Number(x.touched) || x.account.localeCompare(y.account) || (x.assignment ?? '').localeCompare(y.assignment ?? ''))
}
