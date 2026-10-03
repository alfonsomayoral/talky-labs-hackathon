// Lookups behind the evidence viewers: ERP records by file + key, statement lines, book line ids.

import type { BankLine, DatasetCore, EvidenceRef } from '@/domain/types'

/** The ERP record an `erp` evidence points at (an array when the key matches several rows), or null. */
export function findErpRecord(core: DatasetCore, file: string, key: string): unknown {
  const by = <T>(rows: readonly T[] | undefined, pick: (r: T) => unknown) => rows?.find((r) => pick(r) === key) ?? null
  const all = <T>(rows: readonly T[] | undefined, pick: (r: T) => unknown) => {
    const out = (rows ?? []).filter((r) => pick(r) === key)
    return out.length ? out : null
  }
  switch (file) {
    case 'erp/vendors.jsonl':
      return by(core.vendors, (r) => r.id)
    case 'erp/customers.jsonl':
      return by(core.customers, (r) => r.id)
    case 'erp/purchase_orders.jsonl':
      return by(core.purchaseOrders, (r) => r.id)
    case 'erp/ap_invoices.jsonl':
      return by(core.apInvoices, (r) => r.doc_id)
    case 'erp/ap_document_log.jsonl':
      return by(core.apDocumentLog, (r) => r.doc_id)
    case 'erp/contractor_certificates.jsonl':
      return all(core.contractorCertificates, (r) => r.vendor)
    case 'erp/sales_contracts.jsonl':
      return by(core.salesContracts, (r) => r.id)
    case 'erp/ar_invoices.jsonl':
      return by(core.arInvoices, (r) => r.id)
    case 'erp/promissory_notes.jsonl':
      return by(core.promissoryNotes, (r) => r.number)
    case 'erp/factoring_assignments.jsonl':
      return all(core.factoringAssignments, (r) => r.invoice)
    case 'erp/penalty_notices.jsonl':
      return all(core.penaltyNotices, (r) => r.invoice)
    case 'erp/bank_accounts.jsonl':
      return by(core.bankAccounts, (r) => r.id)
    case 'erp/open_items.jsonl':
      return all(core.openItems, (r) => r.partner)
    case 'erp/fx_rates.jsonl':
      return all(core.fxRates, (r) => r.currency)
    case 'erp/intercompany_agreements.json':
      return (core.intercompanyAgreements as unknown as Record<string, unknown> | undefined)?.[key] ?? null
    default:
      return null
  }
}

export interface StatementLineRef {
  account: string
  month: string
  line: BankLine
}

const lineIndex = new WeakMap<DatasetCore, Map<string, StatementLineRef>>()

/** A statement line by id, with its account and month (`YYYY-MM`). */
export function findStatementLine(core: DatasetCore, bankLine: string): StatementLineRef | null {
  let idx = lineIndex.get(core)
  if (!idx) {
    idx = new Map()
    for (const st of core.bankStatements ?? []) for (const line of st.lines) idx.set(line.bank_line, { account: st.account, month: st.month, line })
    lineIndex.set(core, idx)
  }
  return idx.get(bankLine) ?? null
}

/** `<entry id>#<line>` → entry id and 1-based line number. */
export function parseBookLine(bookLine: string): { entryId: string; line: number | null } {
  const i = bookLine.lastIndexOf('#')
  if (i < 0) return { entryId: bookLine, line: null }
  const n = Number(bookLine.slice(i + 1))
  return { entryId: bookLine.slice(0, i), line: Number.isFinite(n) ? n : null }
}

export const fileExtension = (path: string): string => path.split('/').pop()?.split('.').pop()?.toLowerCase() ?? ''

/** Evidence references without repeats, in order. */
export function uniqueRefs(refs: readonly EvidenceRef[]): EvidenceRef[] {
  const seen = new Set<string>()
  return refs.filter((r) => {
    const k = JSON.stringify(r)
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}
