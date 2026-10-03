// Facturación AR: list rows, invoice preview figures, the «a origen − anterior» of a certification and its WIP link.
// Pure functions over the delivered rows and the dataset; ArBillingPage draws them.

import type {
  ArBillingInboxItem,
  ArBillingInvoice,
  ArBillingRow,
  BillingHistoryEntry,
  CloseRow,
  DatasetCore,
  ItemId,
  SalesContract,
  WorkItem,
} from '@/domain/types'
import { closeItemId } from '@/engine'
import { itemEurCents } from '@/features/item/kit'

const str = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)
const num = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)

export interface BillingListRow {
  item: WorkItem
  row: ArBillingRow
  type: string | null
  contract: string | null
  customer: string | null
  /** Billing month `YYYY-MM` (for PPA and market, the month after the production period). */
  month: string | null
  invoiceNumber: string | null
}

/** Number the invoice will carry: the reference of its entry, or the assignment of its 43000000 line. */
export function invoiceNumber(row: ArBillingRow): string | null {
  const je = row.journal_entry
  if (!je) return null
  const ref = str(je.reference)
  if (ref) return ref
  const receivable = (Array.isArray(je.lines) ? je.lines : []).find((l) => l.account === '43000000' && str(l.assignment))
  return str(receivable?.assignment)
}

/** One list row per billing item, with type, contract and customer from the row or its inbox item.json. */
export function billingListRows(items: readonly WorkItem[], rows: readonly ArBillingRow[], inbox: readonly ArBillingInboxItem[]): BillingListRow[] {
  const meta = new Map(inbox.map((b) => [b.item, b.meta]))
  return items
    .filter((it) => it.task === 'ar_billing')
    .map((item) => {
      const row = rows[item.rowIndex]
      const m = meta.get(item.key) ?? null
      return {
        item,
        row,
        type: str(row?.type) ?? str(m?.type),
        contract: str(row?.contract) ?? str(m?.contract),
        customer: str(row?.customer) ?? str(m?.customer),
        month: str(row?.month) ?? str(m?.month),
        invoiceNumber: row ? invoiceNumber(row) : null,
      }
    })
}

export interface InvoiceFigures {
  net: number
  tax: number
  gross: number
  retention: number
  deductions: { code: string; amount: number; account: string | null }[]
  payable: number
  /** gross − retention − Σdeductions, the policy's definition of `payable`. */
  expectedPayable: number
  payableOk: boolean
  linesTotal: number
  linesOk: boolean
}

/** Waterfall of an invoice (net → + tax → − retention → − deductions → payable) with its arithmetic checks (±1 cent). */
export function invoiceFigures(inv: ArBillingInvoice): InvoiceFigures {
  const net = num(inv.net)
  const tax = num(inv.tax)
  const gross = typeof inv.gross === 'number' ? inv.gross : net + tax
  const retention = num(inv.retention)
  const deductions = (Array.isArray(inv.deductions) ? inv.deductions : []).map((d) => ({
    code: str(d.code) ?? 'DEDUCCIÓN',
    amount: num(d.amount),
    account: str(d.account),
  }))
  const payable = num(inv.payable)
  const expectedPayable = gross - retention - deductions.reduce((s, d) => s + d.amount, 0)
  const linesTotal = (Array.isArray(inv.lines) ? inv.lines : []).reduce((s, l) => s + num(l.amount), 0)
  return {
    net,
    tax,
    gross,
    retention,
    deductions,
    payable,
    expectedPayable,
    payableOk: Math.abs(expectedPayable - payable) <= 1,
    linesTotal,
    linesOk: Math.abs(linesTotal - net) <= 1,
  }
}

export interface CertificationCalc {
  /** Last approved certification before this month (null on the first one). */
  previous: { number: number; month: string; approvedOn: string | null } | null
  /** Cumulative of the last approved certification. */
  anterior: number
  /** This certification: the invoice net, or the pending work when it is not billed. */
  presente: number | null
  aOrigen: number | null
  /** Certifications after the last approved one that were never approved (their work is inside `presente`). */
  pendingMonths: string[]
  contractValue: number | null
  /** a origen / contract value. */
  executed: number | null
}

/**
 * «A origen − anterior» (§3.1): the anterior is the cumulative of the last *approved* certification
 * in the billing history, so a month left pending is billed with the next one.
 */
export function certificationCalc(
  contract: string,
  month: string,
  presente: number | null,
  history: readonly BillingHistoryEntry[],
  contracts: readonly SalesContract[],
): CertificationCalc {
  const certs = history
    .filter((h) => h.contract === contract && h.cert && h.month < month)
    .sort((a, b) => a.month.localeCompare(b.month))
  let lastApproved: BillingHistoryEntry | null = null
  for (const h of certs) if (h.cert?.approved) lastApproved = h
  const pendingMonths = certs.filter((h) => !h.cert?.approved && (!lastApproved || h.month > lastApproved.month)).map((h) => h.month)
  const anterior = lastApproved?.cert?.cumulative ?? 0
  const aOrigen = presente === null ? null : anterior + presente
  const value = contracts.find((c) => c.id === contract)?.value ?? null
  return {
    previous: lastApproved?.cert ? { number: lastApproved.cert.number, month: lastApproved.month, approvedOn: lastApproved.cert.approved_on } : null,
    anterior,
    presente,
    aOrigen,
    pendingMonths,
    contractValue: value,
    executed: value && aOrigen !== null ? aOrigen / value : null,
  }
}

export interface WipLink {
  id: ItemId
  company: string
  amount: number
}

/** The `WIP_REVENUE` close row that carries the pending work of a billing item (§5), if delivered. */
export function wipFor(billingItem: string, closeRows: readonly CloseRow[]): WipLink | null {
  const r = closeRows.find((x) => x.type === 'WIP_REVENUE' && x.billing_item === billingItem)
  return r ? { id: closeItemId('WIP_REVENUE', r.company, r.billing_item), company: String(r.company), amount: num(r.amount) } : null
}

export interface BillingSummary {
  invoices: number
  pending: number
  /** EUR cents (3100 at the month-end rate). */
  netEur: number
  payableEur: number
  face: number
  wipEur: number
  /** Pending items without a WIP_REVENUE row in close. */
  pendingWithoutWip: number
}

export function billingSummary(rows: readonly BillingListRow[], closeRows: readonly CloseRow[], core: DatasetCore): BillingSummary {
  const s: BillingSummary = { invoices: 0, pending: 0, netEur: 0, payableEur: 0, face: 0, wipEur: 0, pendingWithoutWip: 0 }
  for (const r of rows) {
    const inv = r.row?.invoice
    if (r.item.outcome === 'INVOICE' && inv) {
      s.invoices++
      s.netEur += itemEurCents(r.item, num(inv.net), core)
      s.payableEur += itemEurCents(r.item, num(inv.payable), core)
      if (inv.face && typeof inv.face === 'object') s.face++
    } else if (r.item.outcome === 'SKIP_PENDING_APPROVAL') {
      s.pending++
      const wip = wipFor(r.item.key, closeRows)
      if (wip) s.wipEur += itemEurCents(r.item, wip.amount, core)
      else s.pendingWithoutWip++
    }
  }
  return s
}
