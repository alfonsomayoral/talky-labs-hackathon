// Lookups over the dataset core used while deriving items (built once per core).

import type {
  ApInboxDoc,
  ArBillingInboxItem,
  ArInvoice,
  BankAccount,
  BankLine,
  Company,
  Customer,
  DatasetCore,
  FxRate,
  Vendor,
} from '@/domain/types'

export interface BankLineRef {
  account: string
  line: BankLine
}

export interface CoreIndex {
  core: DatasetCore
  companies: Map<string, Company>
  vendors: Map<string, Vendor>
  customers: Map<string, Customer>
  bankAccounts: Map<string, BankAccount>
  bankLines: Map<string, BankLineRef>
  apInbox: Map<string, ApInboxDoc>
  billingInbox: Map<string, ArBillingInboxItem>
  arInvoices: Map<string, ArInvoice>
  apInvoiceIds: Set<string>
  /** Last day of the month being closed (`YYYY-MM-DD`), or null when unknown. */
  monthEnd: string | null
}

const cache = new WeakMap<DatasetCore, CoreIndex>()

function lastDay(month: string | undefined): string | null {
  if (!month || !/^\d{4}-\d{2}$/.test(month)) return null
  const [y, m] = month.split('-').map(Number)
  return `${month}-${String(new Date(Date.UTC(y, m, 0)).getUTCDate()).padStart(2, '0')}`
}

export function coreIndex(core: DatasetCore): CoreIndex {
  let idx = cache.get(core)
  if (idx) return idx
  const bankLines = new Map<string, BankLineRef>()
  for (const st of core.bankStatements ?? []) for (const line of st.lines) bankLines.set(line.bank_line, { account: st.account, line })
  idx = {
    core,
    companies: new Map((core.companies ?? []).map((c) => [c.code, c])),
    vendors: new Map((core.vendors ?? []).map((v) => [v.id, v])),
    customers: new Map((core.customers ?? []).map((c) => [c.id, c])),
    bankAccounts: new Map((core.bankAccounts ?? []).map((b) => [b.id, b])),
    bankLines,
    apInbox: new Map((core.apInbox ?? []).map((d) => [d.docId, d])),
    billingInbox: new Map((core.arInbox?.billing ?? []).map((b) => [b.item, b])),
    arInvoices: new Map((core.arInvoices ?? []).map((i) => [i.id, i])),
    apInvoiceIds: new Set((core.apInvoices ?? []).map((i) => i.doc_id)),
    monthEnd: lastDay(core.tasks?.close?.month),
  }
  cache.set(core, idx)
  return idx
}

export const companyCurrency = (idx: CoreIndex, company: unknown): string | null =>
  idx.companies.get(String(company))?.currency ?? null

/** Converts local cents to EUR cents with the latest SYN-BCE rate on or before `date` (EUR passes through). */
export function toEur(amount: number, currency: string | null, rates: readonly FxRate[], date: string | null): number {
  if (!currency || currency === 'EUR') return amount
  let best: FxRate | null = null
  for (const r of rates) {
    if (r.base !== 'EUR' || r.currency !== currency || (date && r.date > date)) continue
    if (!best || r.date > best.date) best = r
  }
  return best ? Math.round(amount / best.rate) : amount
}
