// Bandeja AP view model: pure functions over the delivered ap.jsonl, the WorkItems and the ERP master data.

import type {
  ApInvoice,
  ApDocumentLogEntry,
  ApLine,
  ApRow,
  Company,
  ContractorCertificate,
  EInvoiceSummary,
  GoodsReceipt,
  PurchaseOrder,
  Vendor,
  WorkItem,
} from '@/domain/types'
import { AP_DECISIONS, AP_DOCUMENT_TYPES } from '@/domain/types'
import type { Tone } from '@/components'
import { formatDate } from '@/lib/format'

/** Status colour of each decision (PLAN §5: resolved, blocked or rejected). */
export const DECISION_TONE: Record<string, Tone> = {
  POST: 'ok',
  POST_PAYMENT_BLOCK: 'warn',
  HOLD: 'warn',
  REJECT: 'danger',
  DUPLICATE: 'neutral',
  NOT_INVOICE: 'neutral',
}

// ---------------------------------------------------------------- sankey: document type → decision
export interface SankeyNode {
  id: string
  side: 'type' | 'decision'
  key: string
  count: number
}

export interface SankeyLink {
  source: string
  target: string
  type: string
  decision: string
  count: number
}

export interface ApSankey {
  types: SankeyNode[]
  decisions: SankeyNode[]
  links: SankeyLink[]
  total: number
}

const orderBy = (order: readonly string[]) => (a: string, b: string) => {
  const ia = order.indexOf(a)
  const ib = order.indexOf(b)
  return (ia < 0 ? order.length : ia) - (ib < 0 ? order.length : ib) || a.localeCompare(b)
}

export function apSankey(rows: readonly Pick<ApRow, 'document_type' | 'decision'>[]): ApSankey {
  const pairs = new Map<string, SankeyLink>()
  const typeCount = new Map<string, number>()
  const decisionCount = new Map<string, number>()
  for (const r of rows) {
    const type = String(r.document_type ?? 'UNKNOWN')
    const decision = String(r.decision ?? 'UNKNOWN')
    typeCount.set(type, (typeCount.get(type) ?? 0) + 1)
    decisionCount.set(decision, (decisionCount.get(decision) ?? 0) + 1)
    const id = `${type}>${decision}`
    const link = pairs.get(id)
    if (link) link.count++
    else pairs.set(id, { source: `type:${type}`, target: `decision:${decision}`, type, decision, count: 1 })
  }
  const byType = orderBy(AP_DOCUMENT_TYPES)
  const byDecision = orderBy(AP_DECISIONS)
  const types = [...typeCount.keys()].sort(byType).map((key): SankeyNode => ({ id: `type:${key}`, side: 'type', key, count: typeCount.get(key)! }))
  const decisions = [...decisionCount.keys()]
    .sort(byDecision)
    .map((key): SankeyNode => ({ id: `decision:${key}`, side: 'decision', key, count: decisionCount.get(key)! }))
  const links = [...pairs.values()].sort((a, b) => byType(a.type, b.type) || byDecision(a.decision, b.decision))
  return { types, decisions, links, total: rows.length }
}

// ---------------------------------------------------------------- facets and filtering
export interface ApFilter {
  decisions: string[]
  reasons: string[]
  types: string[]
  /** Items behind a ProcessMap node or a sankey link; null = no restriction. */
  only: ReadonlySet<string> | null
  query: string
}

export const EMPTY_FILTER: ApFilter = { decisions: [], reasons: [], types: [], only: null, query: '' }

export const NO_REASON = '—'

export function isFiltering(f: ApFilter): boolean {
  return f.decisions.length > 0 || f.reasons.length > 0 || f.types.length > 0 || f.only !== null || f.query.trim() !== ''
}

/** Item reasons, with NO_REASON standing in for an empty list (POST, NOT_INVOICE). */
const reasonsOf = (it: WorkItem): string[] => (it.reasons.length ? it.reasons : [NO_REASON])

export interface ApListRow {
  item: WorkItem
  row: ApRow
}

export function apListRows(items: readonly WorkItem[], rows: readonly ApRow[]): ApListRow[] {
  const out: ApListRow[] = []
  for (const item of items) {
    if (item.task !== 'ap') continue
    const row = rows[item.rowIndex]
    if (row) out.push({ item, row })
  }
  return out
}

function matches(r: ApListRow, f: ApFilter, skip?: 'decisions' | 'reasons' | 'types'): boolean {
  if (f.only && !f.only.has(r.item.id)) return false
  if (skip !== 'decisions' && f.decisions.length && !f.decisions.includes(r.item.outcome)) return false
  if (skip !== 'types' && f.types.length && !f.types.includes(String(r.row.document_type))) return false
  if (skip !== 'reasons' && f.reasons.length && !reasonsOf(r.item).some((x) => f.reasons.includes(x))) return false
  const q = f.query.trim().toLowerCase()
  if (q) {
    const hay = [r.item.key, r.row.invoice_number, r.row.vendor_id, r.item.counterparty, r.row.company].filter(Boolean).join(' ').toLowerCase()
    if (!hay.includes(q)) return false
  }
  return true
}

export function filterRows(rows: readonly ApListRow[], f: ApFilter): ApListRow[] {
  return isFiltering(f) ? rows.filter((r) => matches(r, f)) : [...rows]
}

/** Counts per facet value among the rows that pass every other facet (so counts answer «if I add this»). */
export function facetCounts(rows: readonly ApListRow[], f: ApFilter): { decisions: Map<string, number>; reasons: Map<string, number>; types: Map<string, number> } {
  const decisions = new Map<string, number>()
  const reasons = new Map<string, number>()
  const types = new Map<string, number>()
  const bump = (m: Map<string, number>, k: string) => m.set(k, (m.get(k) ?? 0) + 1)
  for (const r of rows) {
    if (matches(r, f, 'decisions')) bump(decisions, r.item.outcome)
    if (matches(r, f, 'reasons')) for (const x of reasonsOf(r.item)) bump(reasons, x)
    if (matches(r, f, 'types')) bump(types, String(r.row.document_type))
  }
  return { decisions, reasons, types }
}

// ---------------------------------------------------------------- extracted fields vs master
export type CompareState = 'match' | 'mismatch' | 'explained' | 'unknown'

export interface CompareField {
  id: string
  label: string
  document: string | null
  master: string | null
  state: CompareState
  note: string | null
}

const norm = (s: string | null | undefined) => (s ?? '').replace(/[\s-]/g, '').toUpperCase()
const sameTaxId = (doc: string | null, ...master: (string | null | undefined)[]) => {
  const d = norm(doc).replace(/^[A-Z]{2}(?=[A-Z0-9]{8,}$)/, '')
  return master.some((m) => {
    const n = norm(m)
    return n !== '' && (n === norm(doc) || n.replace(/^[A-Z]{2}(?=[A-Z0-9]{8,}$)/, '') === d)
  })
}

export interface MasterCompareInput {
  row: Pick<ApRow, 'company' | 'vendor_id' | 'currency' | 'invoice_date' | 'withholding' | 'payee' | 'reasons'>
  vendor: Vendor | null
  company: Company | null
  einvoice: EInvoiceSummary | null
  certificates: readonly ContractorCertificate[]
  /** Sender address of the message (`from`, or `uploaded_by` on the portal). */
  sender: string | null
}

const domainOf = (address: string | null | undefined) => {
  const at = (address ?? '').lastIndexOf('@')
  return at >= 0 ? address!.slice(at + 1).trim().toLowerCase() : null
}

/**
 * The fields the cascade checks, side by side: what the document says (from the e-invoice when there is
 * one, else what the agent extracted) and what the master data holds.
 */
export function masterCompare({ row, vendor, company, einvoice, certificates, sender }: MasterCompareInput): CompareField[] {
  const out: CompareField[] = []
  const field = (f: Omit<CompareField, 'note'> & { note?: string | null }) => out.push({ note: null, ...f })

  field({
    id: 'vendor',
    label: 'Proveedor',
    document: einvoice?.seller.name ?? row.vendor_id ?? null,
    master: vendor ? `${vendor.id} · ${vendor.name}` : null,
    state: vendor ? 'match' : 'mismatch',
    note: vendor ? null : 'No está dado de alta en el maestro',
  })

  if (einvoice?.seller.taxId || vendor) {
    const doc = einvoice?.seller.taxId ?? null
    field({
      id: 'seller_tax_id',
      label: 'NIF del emisor',
      document: doc,
      master: vendor?.tax_id ?? null,
      state: !doc || !vendor ? 'unknown' : sameTaxId(doc, vendor.tax_id, vendor.vat_id) ? 'match' : 'mismatch',
    })
  }

  const buyer = einvoice?.buyer.taxId ?? null
  field({
    id: 'addressee',
    label: 'Destinatario',
    document: buyer ?? row.company ?? null,
    master: company ? `${company.code} · ${company.tax_id}` : null,
    state: !company ? 'unknown' : buyer ? (sameTaxId(buyer, company.tax_id, company.vat_id) ? 'match' : 'mismatch') : 'unknown',
    note: vendor && company && !vendor.companies.includes(company.code) ? `El proveedor trabaja con ${vendor.companies.join(', ')}` : null,
  })

  const senderDomain = domainOf(sender)
  const vendorDomain = domainOf(vendor?.email)
  if (senderDomain) {
    field({
      id: 'sender',
      label: 'Dominio del remitente',
      document: senderDomain,
      master: vendorDomain,
      state: !vendorDomain ? 'unknown' : senderDomain === vendorDomain ? 'match' : 'mismatch',
      note: vendorDomain && senderDomain !== vendorDomain ? 'Distinto del correo de la ficha: posible suplantación' : null,
    })
  }

  const docIban = einvoice?.iban ?? null
  const masterIban = vendor?.bank.iban ?? null
  let ibanState: CompareState = 'unknown'
  let ibanNote: string | null = null
  if (docIban && masterIban) {
    if (norm(docIban) === norm(masterIban)) ibanState = 'match'
    else if (vendor?.alternative_payee && norm(vendor.alternative_payee.iban) === norm(docIban)) {
      ibanState = 'explained'
      ibanNote = `Cuenta del factor ${vendor.alternative_payee.name} (cesión desde ${vendor.alternative_payee.from_date})`
    } else if (vendor?.bank_history.some((h) => norm(h.iban) === norm(docIban))) {
      ibanState = 'mismatch'
      ibanNote = 'Es una cuenta antigua de la ficha, ya sustituida'
    } else {
      ibanState = 'mismatch'
      ibanNote = 'No figura en la ficha ni en una cesión registrada'
    }
  } else if (!docIban) ibanNote = 'El documento no trae IBAN legible'
  if (row.reasons?.includes('BANK_DETAILS_CHANGED') && ibanState !== 'mismatch') {
    ibanState = 'mismatch'
    ibanNote = 'El agente detectó un IBAN distinto del de la ficha'
  }
  field({ id: 'iban', label: 'IBAN', document: docIban, master: masterIban, state: ibanState, note: ibanNote })

  const currency = einvoice?.currency ?? row.currency ?? null
  field({
    id: 'currency',
    label: 'Moneda',
    document: currency,
    master: vendor?.currency ?? null,
    state: !currency || !vendor ? 'unknown' : currency === vendor.currency ? 'match' : 'mismatch',
  })

  if (vendor?.withholding || (row.withholding ?? 0) > 0) {
    const docWithheld = einvoice ? (einvoice.withheld ?? 0) > 0 : (row.withholding ?? 0) > 0
    field({
      id: 'withholding',
      label: 'Retención',
      document: docWithheld ? 'Practicada' : 'No practicada',
      master: vendor?.withholding ?? 'Sin retención',
      state: !vendor ? 'unknown' : Boolean(vendor.withholding) === docWithheld ? 'match' : 'mismatch',
    })
  }

  const certs = vendor ? certificates.filter((c) => c.vendor === vendor.id) : []
  if (certs.length && row.invoice_date) {
    const date = row.invoice_date
    const valid = certs.some((c) => c.issued_on <= date && date <= c.valid_until)
    const last = certs.reduce((a, b) => (b.valid_until > a.valid_until ? b : a))
    field({
      id: 'certificate',
      label: 'Certificado art. 43',
      document: formatDate(date),
      master: `Vigente hasta ${formatDate(last.valid_until)}`,
      state: valid ? 'match' : 'mismatch',
      note: valid ? null : 'Caducado a la fecha de la factura',
    })
  }

  return out
}

// ---------------------------------------------------------------- action data of a NOT_INVOICE document

export interface ActionDetail {
  label: string
  value: string | number
  kind: 'text' | 'mono' | 'money'
}

const ACTION_FIELDS: Record<string, { label: string; kind: 'text' | 'mono' | 'money' | 'date' | 'days' | 'bool' }> = {
  ref: { label: 'Referencia', kind: 'mono' },
  reference: { label: 'Referencia', kind: 'mono' },
  amount: { label: 'Importe', kind: 'money' },
  factor: { label: 'Factor', kind: 'text' },
  iban: { label: 'IBAN', kind: 'mono' },
  old_iban: { label: 'IBAN anterior', kind: 'mono' },
  new_iban: { label: 'IBAN nuevo', kind: 'mono' },
  certificate: { label: 'Certificado bancario', kind: 'bool' },
  effective: { label: 'Desde', kind: 'date' },
  valid_until: { label: 'Vigente hasta', kind: 'date' },
  as_of: { label: 'A fecha de', kind: 'date' },
  valid_days: { label: 'Validez', kind: 'days' },
}

/** `action_data` of the delivered row as label/value pairs, in the order the agent wrote them. */
export function actionDetails(data: unknown): ActionDetail[] {
  if (!data || typeof data !== 'object') return []
  return Object.entries(data as Record<string, unknown>)
    .filter(([, v]) => v !== null && v !== undefined && v !== '')
    .map(([k, v]): ActionDetail => {
      const f = ACTION_FIELDS[k]
      if (!f) return { label: k, value: typeof v === 'object' ? JSON.stringify(v) : String(v), kind: 'text' }
      if (f.kind === 'money' && typeof v === 'number') return { label: f.label, value: v, kind: 'money' }
      if (f.kind === 'date') return { label: f.label, value: formatDate(String(v)), kind: 'text' }
      if (f.kind === 'days') return { label: f.label, value: `${v} días`, kind: 'text' }
      if (f.kind === 'bool') return { label: f.label, value: v ? 'Sí' : 'No', kind: 'text' }
      return { label: f.label, value: String(v), kind: f.kind === 'mono' ? 'mono' : 'text' }
    })
}

// ---------------------------------------------------------------- line-by-line match with PO and goods receipt
export const PRICE_TOLERANCE_RATIO = 0.02
export const PRICE_TOLERANCE_CENTS = 15_000

export type LineState = 'no_po' | 'ok' | 'within_tolerance' | 'price_variance' | 'not_received' | 'po_missing'

export interface LineMatch {
  index: number
  line: ApLine
  po: string | null
  poItem: number | null
  description: string | null
  orderedQtyMilli: number | null
  unitPrice: number | null
  receipts: GoodsReceipt[]
  receivedQtyMilli: number
  /** Σ receipt amounts (quantity × PO price). */
  receivedValue: number
  /** Invoiced − received value. */
  variance: number
  state: LineState
}

const lineReceipts = (line: ApLine): string[] | null => {
  const ids = (line as Record<string, unknown>).goods_receipts
  return Array.isArray(ids) ? ids.map(String) : null
}

/** Over the tolerance of §2.2.3: more than 2 % of the receipt value or more than 150 € on the line. */
export function overTolerance(variance: number, receivedValue: number): boolean {
  return variance > PRICE_TOLERANCE_CENTS || (receivedValue > 0 && variance > receivedValue * PRICE_TOLERANCE_RATIO)
}

export function lineMatches(lines: readonly ApLine[], orders: readonly PurchaseOrder[], receipts: readonly GoodsReceipt[]): LineMatch[] {
  const poById = new Map(orders.map((p) => [p.id, p]))
  const grById = new Map(receipts.map((g) => [g.id, g]))
  return lines.map((line, index): LineMatch => {
    const po = line.po ? String(line.po) : null
    const poItem = line.po_item === null || line.po_item === undefined ? null : Number(line.po_item)
    const base = { index, line, po, poItem, description: null, orderedQtyMilli: null, unitPrice: null, receipts: [], receivedQtyMilli: 0, receivedValue: 0, variance: 0 }
    if (!po) return { ...base, state: 'no_po' }
    const order = poById.get(po)
    const item = order?.items.find((i) => i.item === poItem) ?? null
    if (!order || !item) return { ...base, state: 'po_missing' }
    const explicit = lineReceipts(line)
    const grs = explicit ? explicit.map((id) => grById.get(id)).filter((g): g is GoodsReceipt => !!g) : receipts.filter((g) => g.po === po && g.po_item === poItem)
    const receivedQtyMilli = grs.reduce((s, g) => s + g.quantity_milli, 0)
    const receivedValue = grs.reduce((s, g) => s + g.amount, 0)
    const variance = line.amount - receivedValue
    const state: LineState = !grs.length ? 'not_received' : variance === 0 ? 'ok' : overTolerance(variance, receivedValue) ? 'price_variance' : 'within_tolerance'
    return { ...base, description: item.description, orderedQtyMilli: item.quantity_milli, unitPrice: item.unit_price, receipts: grs, receivedQtyMilli, receivedValue, variance, state }
  })
}

// ---------------------------------------------------------------- duplicate target
export type DuplicateTarget =
  | { kind: 'month'; docId: string; row: ApRow }
  | { kind: 'history'; docId: string; invoice: ApInvoice | null; log: ApDocumentLogEntry | null }
  | { kind: 'missing'; docId: string }

export function duplicateTarget(
  duplicateOf: string | null | undefined,
  rows: readonly ApRow[],
  history: { apInvoices: readonly ApInvoice[]; apDocumentLog: readonly ApDocumentLogEntry[] },
): DuplicateTarget | null {
  if (!duplicateOf) return null
  const docId = String(duplicateOf)
  const row = rows.find((r) => r.doc_id === docId)
  if (row) return { kind: 'month', docId, row }
  const invoice = history.apInvoices.find((i) => i.doc_id === docId) ?? null
  const log = history.apDocumentLog.find((l) => l.doc_id === docId) ?? null
  return invoice || log ? { kind: 'history', docId, invoice, log } : { kind: 'missing', docId }
}

/** Documents of this month that point at `docId` as their original. */
export function duplicatesOf(docId: string, rows: readonly ApRow[]): string[] {
  return rows.filter((r) => r.duplicate_of === docId).map((r) => r.doc_id)
}

/** Splits `text` around what differs from `reference`: the common start, the changed middle and the common end. */
export function textDiff(text: string, reference: string): { before: string; changed: string; after: string } {
  let start = 0
  while (start < text.length && start < reference.length && text[start] === reference[start]) start++
  let end = 0
  while (end < text.length - start && end < reference.length - start && text[text.length - 1 - end] === reference[reference.length - 1 - end]) end++
  return { before: text.slice(0, start), changed: text.slice(start, text.length - end), after: text.slice(text.length - end) }
}
