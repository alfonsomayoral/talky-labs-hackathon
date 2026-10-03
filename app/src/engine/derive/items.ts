// One WorkItem per unit of work in the deliverables (PLAN §5), with its journal entries.

import type {
  AgentEvent,
  ApRow,
  ArBillingRow,
  ArCashRow,
  BankRecRow,
  CloseRow,
  DatasetCore,
  EvidenceRef,
  IcRow,
  ItemId,
  ItemStatus,
  JournalEntryOut,
  Provenance,
  RunBundle,
  WorkItem,
} from '@/domain/types'
import {
  AP_DECISION_CATALOG,
  AP_DOCUMENT_TYPE_CATALOG,
  AP_REASON_CATALOG,
  AR_RESIDUAL_CATALOG,
  BANK_CATEGORY_CATALOG,
  CLOSE_TYPE_CATALOG,
  IC_CAUSE_CATALOG,
  outcomeEntry,
  type ArCashOutcome,
  type PolicyEntry,
} from '@/domain/catalog/policy'
import { apItemId, arBillingItemId, arCashItemId, bankItemId, bankRowKeys, closeItemId, icItemId } from '../ids'
import { asJournalEntry, effectiveDeliverables, entryDebit, rowEntries } from '../ledger/entries'
import { closeKeyField, closeKeyParts } from '../score/tasks'
import { coreIndex, companyCurrency, type CoreIndex } from './context'

export interface BuiltItems {
  items: WorkItem[]
  /** Journal entries of each item (AP/AR billing/close journal_entry, adjustments of the others). */
  entries: Map<ItemId, JournalEntryOut[]>
}

const num = (x: unknown): number | null => (typeof x === 'number' && Number.isFinite(x) ? x : null)
const str = (x: unknown): string | null => (typeof x === 'string' && x ? x : null)
const uniq = <T>(xs: T[]): T[] => [...new Set(xs)]
/** Policy sections of catalog entries (or literal sections), deduplicated. */
const refs = (...xs: (PolicyEntry | string | null | undefined)[]): string[] =>
  uniq(xs.flatMap((x) => (!x ? [] : typeof x === 'string' ? [x] : [x.section])))

const BILLING_TYPE_LABELS: Record<string, string> = {
  OBRA_CERTIFICATION: 'Certificación de obra',
  SERVICE_MONTHLY: 'Servicio mensual',
  PRICE_REVISION: 'Revisión de precios',
  PPA: 'Energía PPA',
  MARKET_SETTLEMENT: 'Liquidación de mercado',
}

interface Ctx {
  idx: CoreIndex
  run: RunBundle
  eventsByItem: Map<ItemId, AgentEvent[]>
  items: WorkItem[]
  entries: Map<ItemId, JournalEntryOut[]>
}

function provenanceOf(c: Ctx, id: ItemId): { provenance: Provenance; confidence: number | null } {
  if (c.run.source === 'golden') return { provenance: 'REFERENCE', confidence: null }
  const ev = c.eventsByItem.get(id) ?? []
  const decide = [...ev].reverse().find((e) => e.kind === 'DECIDE' && typeof e.confidence === 'number')
  const human = ev.some((e) => e.kind === 'HUMAN_OVERRIDE')
  return { provenance: human ? 'HUMAN' : ev.some((e) => e.model) ? 'MODEL' : 'RULE', confidence: decide?.confidence ?? null }
}

type Draft = Omit<WorkItem, 'provenance' | 'confidence' | 'tbImpact'>

function push(c: Ctx, draft: Draft, entries: JournalEntryOut[]) {
  c.items.push({ ...draft, ...provenanceOf(c, draft.id), tbImpact: entries.reduce((s, e) => s + entryDebit(e), 0) })
  c.entries.set(draft.id, entries)
}

const rowJournal = (task: Parameters<typeof rowEntries>[0], row: unknown): JournalEntryOut[] => rowEntries(task, row).map(asJournalEntry)

const vendorRef = (id: unknown): EvidenceRef[] => (str(id) ? [{ kind: 'erp', file: 'erp/vendors.jsonl', key: id as string }] : [])
const customerRef = (id: unknown): EvidenceRef[] => (str(id) ? [{ kind: 'erp', file: 'erp/customers.jsonl', key: id as string }] : [])

// ---------------------------------------------------------------- AP
const AP_STATUS: Record<string, ItemStatus> = {
  POST: 'AUTO',
  NOT_INVOICE: 'AUTO',
  DUPLICATE: 'AUTO',
  POST_PAYMENT_BLOCK: 'BLOCKED',
  HOLD: 'BLOCKED',
  REJECT: 'BLOCKED',
}

function apItems(c: Ctx, rows: ApRow[]) {
  const { idx } = c
  rows.forEach((r, rowIndex) => {
    const id = apItemId(r.doc_id)
    const vendor = idx.vendors.get(String(r.vendor_id))
    const inbox = idx.apInbox.get(String(r.doc_id))
    const docType = AP_DOCUMENT_TYPE_CATALOG[r.document_type]?.label ?? 'Documento'
    const reasons = (Array.isArray(r.reasons) ? r.reasons : []).map(String)
    const evidence: EvidenceRef[] = []
    if (inbox) {
      evidence.push({ kind: 'doc', path: `inbox/ap/${inbox.docId}/message.json`, locator: 'mensaje' })
      for (const path of inbox.files) evidence.push({ kind: 'doc', path })
    }
    evidence.push(...vendorRef(r.vendor_id))
    for (const po of uniq((Array.isArray(r.lines) ? r.lines : []).map((l) => str(l.po)).filter((x): x is string => !!x))) {
      evidence.push({ kind: 'erp', file: 'erp/purchase_orders.jsonl', key: po })
    }
    const dup = str(r.duplicate_of)
    if (dup) {
      const first = idx.apInbox.get(dup)
      if (first) evidence.push({ kind: 'doc', path: first.files[0] ?? `inbox/ap/${dup}/message.json`, locator: 'documento original' })
      else evidence.push({ kind: 'erp', file: idx.apInvoiceIds.has(dup) ? 'erp/ap_invoices.jsonl' : 'erp/ap_document_log.jsonl', key: dup })
    }
    if (r.payment_block && r.vendor_id) evidence.push({ kind: 'erp', file: 'erp/contractor_certificates.jsonl', key: String(r.vendor_id) })
    const entries = rowJournal('ap', r)
    push(
      c,
      {
        id,
        task: 'ap',
        key: String(r.doc_id),
        company: str(r.company),
        title: [docType, str(r.invoice_number), '·', vendor?.name ?? (r.vendor_id ? String(r.vendor_id) : 'proveedor sin alta')]
          .filter(Boolean)
          .join(' '),
        counterparty: vendor?.name ?? null,
        amount: num(r.gross) ?? num(r.net) ?? num(r.payable),
        currency: str(r.currency) ?? companyCurrency(idx, r.company),
        date: str(r.invoice_date) ?? inbox?.message.received_at?.slice(0, 10) ?? null,
        status: AP_STATUS[String(r.decision)] ?? 'OPEN',
        outcome: String(r.decision ?? 'UNKNOWN'),
        reasons,
        policyRefs: refs(
          r.document_type !== 'INVOICE' ? AP_DOCUMENT_TYPE_CATALOG[r.document_type] : null,
          AP_DECISION_CATALOG[r.decision],
          ...reasons.map((x) => AP_REASON_CATALOG[x as keyof typeof AP_REASON_CATALOG]),
          r.payee ? '§2.2' : null,
          entries.length ? '§2.3' : null,
        ),
        evidence,
        rowIndex,
      },
      entries,
    )
  })
}

// ---------------------------------------------------------------- AR billing
function arBillingItems(c: Ctx, rows: ArBillingRow[]) {
  const { idx } = c
  rows.forEach((r, rowIndex) => {
    const inbox = idx.billingInbox.get(String(r.billing_item))
    const meta = inbox?.meta
    const entries = rowJournal('ar_billing', r)
    const company = str(r.company) ?? entries[0]?.company ?? meta?.company ?? null
    const customerId = str(r.customer) ?? meta?.customer ?? null
    const customer = customerId ? idx.customers.get(customerId) : undefined
    const type = str(r.type) ?? meta?.type ?? null
    const contract = str(r.contract) ?? meta?.contract ?? null
    const inv = r.invoice
    const evidence: EvidenceRef[] = (inbox?.files ?? []).map((path) => ({ kind: 'doc', path }))
    evidence.push(...customerRef(customerId))
    if (contract) evidence.push({ kind: 'erp', file: 'erp/sales_contracts.jsonl', key: contract })
    push(
      c,
      {
        id: arBillingItemId(r.billing_item),
        task: 'ar_billing',
        key: String(r.billing_item),
        company,
        title: [BILLING_TYPE_LABELS[type ?? ''] ?? 'Facturación', contract, '·', customer?.name ?? customerId ?? String(r.billing_item)]
          .filter(Boolean)
          .join(' '),
        counterparty: customer?.name ?? null,
        amount: inv ? (num(inv.gross) ?? (num(inv.net) ?? 0) + (num(inv.tax) ?? 0)) : null,
        currency: str(inv?.currency) ?? companyCurrency(idx, company),
        date: str(inv?.date) ?? idx.monthEnd,
        status: r.expected === 'INVOICE' ? 'AUTO' : r.expected === 'SKIP_PENDING_APPROVAL' ? 'BLOCKED' : 'OPEN',
        outcome: String(r.expected ?? 'UNKNOWN'),
        reasons: [],
        policyRefs: refs(outcomeEntry('ar_billing', String(r.expected)) ?? '§3.1'),
        evidence,
        rowIndex,
      },
      entries,
    )
  })
}

// ---------------------------------------------------------------- AR cash
function arCashOutcome(idx: CoreIndex, r: ArCashRow): ArCashOutcome {
  const apps = Array.isArray(r.applications) ? r.applications : []
  const residuals = Array.isArray(r.residuals) ? r.residuals : []
  if (residuals.length) return 'APPLIED_WITH_DIFFERENCES'
  if (!apps.length) return 'NOT_APPLIED'
  const partial = apps.some((a) => {
    const payable = a.invoice ? idx.arInvoices.get(a.invoice)?.payable : undefined
    return typeof payable === 'number' && typeof a.amount === 'number' && a.amount < payable - 1
  })
  return partial ? 'PARTIAL' : 'APPLIED'
}

function arCashItems(c: Ctx, rows: ArCashRow[]) {
  const { idx } = c
  rows.forEach((r, rowIndex) => {
    const ref = idx.bankLines.get(String(r.bank_line))
    const entries = rowJournal('ar_cash', r)
    const company =
      str(r.company) ?? str(r.adjustment?.[0]?.company) ?? (ref ? (idx.bankAccounts.get(ref.account)?.company ?? null) : null)
    const customer = idx.customers.get(String(r.customer))
    const apps = Array.isArray(r.applications) ? r.applications : []
    const residuals = Array.isArray(r.residuals) ? r.residuals : []
    const evidence: EvidenceRef[] = []
    if (ref) evidence.push({ kind: 'bank', account: ref.account, bank_line: String(r.bank_line) })
    evidence.push(...customerRef(r.customer))
    for (const a of apps) {
      if (a.invoice) evidence.push({ kind: 'erp', file: 'erp/ar_invoices.jsonl', key: a.invoice })
      else if (a.pagare) evidence.push({ kind: 'erp', file: 'erp/promissory_notes.jsonl', key: a.pagare })
    }
    const amount = num(ref?.line.amount) ?? num(r.amount) ?? apps.reduce((s, a) => s + (num(a.amount) ?? 0), 0)
    const outcome = arCashOutcome(idx, r)
    push(
      c,
      {
        id: arCashItemId(r.bank_line),
        task: 'ar_cash',
        key: String(r.bank_line),
        company,
        title: `Cobro ${String(r.bank_line)} · ${customer?.name ?? (r.customer ? String(r.customer) : (ref?.line.text ?? 'sin cliente'))}`,
        counterparty: customer?.name ?? null,
        amount,
        currency: ref?.line.currency ?? companyCurrency(idx, company),
        date: ref?.line.booking_date ?? str(r.date),
        status: 'AUTO',
        outcome,
        reasons: uniq(residuals.map((x) => String(x.type))),
        policyRefs: refs(outcomeEntry('ar_cash', outcome), ...residuals.map((x) => AR_RESIDUAL_CATALOG[x.type])),
        evidence,
        rowIndex,
      },
      entries,
    )
  })
}

// ---------------------------------------------------------------- bank reconciliation
interface BankDraft {
  draft: Draft
  category: string | null
  amount: number | null
  entries: JournalEntryOut[]
}

function bankItems(c: Ctx, rows: BankRecRow[]) {
  const { idx } = c
  rows.forEach((r, rowIndex) => {
    const account = String(r.account)
    const bank = idx.bankAccounts.get(account)
    const currency = bank?.currency ?? companyCurrency(idx, r.company)
    const keys = bankRowKeys(r)
    const lineOf = (bl: unknown) => idx.bankLines.get(String(bl))?.line
    const drafts: BankDraft[] = []
    const base = { task: 'bank_rec' as const, company: str(r.company) ?? bank?.company ?? null, counterparty: bank?.bank ?? null, currency, reasons: [] as string[], rowIndex }
    const matches = Array.isArray(r.matches) ? r.matches : []
    matches.forEach((m, i) => {
      const banks = Array.isArray(m.bank_lines) ? m.bank_lines.map(String) : []
      const books = Array.isArray(m.book_lines) ? m.book_lines.map(String) : []
      const amounts = banks.map((b) => lineOf(b)?.amount).filter((a): a is number => typeof a === 'number')
      const category = str(m.category) ?? 'MATCH'
      drafts.push({
        category: category === 'MATCH' ? null : category,
        amount: amounts.length ? amounts.reduce((s, a) => s + a, 0) : null,
        entries: [],
        draft: {
          ...base,
          id: bankItemId(account, keys.matches[i]),
          key: `${account}/${keys.matches[i]}`,
          title: `Casación ${banks.join(', ') || 'sin línea'} ↔ ${books.length} ${books.length === 1 ? 'apunte' : 'apuntes'}`,
          amount: amounts.length ? amounts.reduce((s, a) => s + a, 0) : null,
          date: lineOf(banks[0])?.booking_date ?? null,
          status: 'AUTO',
          outcome: category,
          policyRefs: refs(outcomeEntry('bank_rec', category)),
          evidence: [
            ...banks.map((b): EvidenceRef => ({ kind: 'bank', account, bank_line: b })),
            ...books.map((b): EvidenceRef => ({ kind: 'journal', book_line: b })),
          ],
        },
      })
    })
    const categories = new Set((Array.isArray(r.adjustments) ? r.adjustments : []).map((a) => String(a.category)))
    const unmatched = [
      ...(Array.isArray(r.unmatched_bank) ? r.unmatched_bank : []).map((x, i) => ({ side: 'bank' as const, line: String(x.bank_line), x, key: keys.unmatchedBank[i] })),
      ...(Array.isArray(r.unmatched_book) ? r.unmatched_book : []).map((x, i) => ({ side: 'book' as const, line: String(x.book_line), x, key: keys.unmatchedBook[i] })),
    ]
    for (const u of unmatched) {
      const category = String(u.x.category)
      const label = BANK_CATEGORY_CATALOG[category as keyof typeof BANK_CATEGORY_CATALOG]?.label ?? category
      const bl = u.side === 'bank' ? lineOf(u.line) : undefined
      const amount = num(bl?.amount) ?? num((u.x as Record<string, unknown>).amount)
      drafts.push({
        category,
        amount,
        entries: [],
        draft: {
          ...base,
          id: bankItemId(account, u.key),
          key: `${account}/${u.key}`,
          title: u.side === 'bank' ? `${label} · ${bl?.text ?? u.line}` : `${label} · apunte ${u.line}`,
          amount,
          date: bl?.booking_date ?? null,
          status: categories.has(category) ? 'AUTO' : 'OPEN',
          outcome: category,
          policyRefs: refs(outcomeEntry('bank_rec', category)),
          evidence: [u.side === 'bank' ? { kind: 'bank', account, bank_line: u.line } : { kind: 'journal', book_line: u.line }],
        },
      })
    }
    assignAdjustments(r, bank?.gl_account ?? null, drafts, (adjIndex, category, entry) => {
      const label = BANK_CATEGORY_CATALOG[category as keyof typeof BANK_CATEGORY_CATALOG]?.label ?? category
      drafts.push({
        category,
        amount: entryDebit(entry),
        entries: [entry],
        draft: {
          ...base,
          id: bankItemId(account, `adj-${adjIndex + 1}`),
          key: `${account}/adj-${adjIndex + 1}`,
          title: `Ajuste sin partida · ${label}`,
          amount: entryDebit(entry),
          date: null,
          status: 'AUTO',
          outcome: category,
          policyRefs: refs(outcomeEntry('bank_rec', category)),
          evidence: [],
        },
      })
    })
    for (const d of drafts) push(c, d.draft, d.entries)
  })
}

/**
 * Each adjustment goes to one item of its category: the one whose bank amount equals the
 * adjustment's movement on the bank GL account, else the first without an adjustment yet.
 * Adjustments with no item of their category become their own item.
 */
function assignAdjustments(
  row: BankRecRow,
  gl: string | null,
  drafts: BankDraft[],
  orphan: (index: number, category: string, entry: JournalEntryOut) => void,
) {
  const entries = rowEntries('bank_rec', row).map(asJournalEntry)
  const adjustments = Array.isArray(row.adjustments) ? row.adjustments : []
  adjustments.forEach((a, i) => {
    const entry = entries[i]
    const category = String(a.category)
    const pool = drafts.filter((d) => d.category === category)
    if (!pool.length) return orphan(i, category, entry)
    const onBank = entry.lines
      .filter((l) => (gl ? String(l.account) === gl : String(l.account).startsWith('572')))
      .reduce((s, l) => s + (Number(l.debit) || 0) - (Number(l.credit) || 0), 0)
    const target = pool.find((d) => !d.entries.length && d.amount === onBank) ?? pool.find((d) => !d.entries.length) ?? pool[0]
    target.entries.push(entry)
  })
}

// ---------------------------------------------------------------- intercompany
const IC_EVIDENCE_KEY: Record<string, string> = {
  INTEREST_DAY_COUNT: 'loan',
  POOLING_NOT_BOOKED: 'cash_pooling',
  WRONG_TRADING_PARTNER: 'cash_pooling',
  INVOICE_IN_TRANSIT: 'management_fees',
  DUPLICATE_POSTING: 'management_fees',
}

function icItems(c: Ctx, rows: IcRow[]) {
  const { idx } = c
  rows.forEach((r, rowIndex) => {
    const pair = (Array.isArray(r.pair) ? [...r.pair] : []).map(String).sort()
    const entries = rowJournal('ic', r)
    const company = str(r.responsible) ?? str(r.adjustment?.[0]?.company) ?? pair[0] ?? null
    const other = pair.find((p) => p !== company) ?? null
    const cause = String(r.cause)
    const entry = IC_CAUSE_CATALOG[cause as keyof typeof IC_CAUSE_CATALOG]
    const adjusted = Array.isArray(r.adjustment) && r.adjustment.length > 0
    push(
      c,
      {
        id: icItemId(pair, cause),
        task: 'ic',
        key: `${pair.join('-')}/${cause}`,
        company,
        title: `${entry?.label ?? cause} · ${pair.join('–')}`,
        counterparty: other ? (idx.companies.get(other)?.name ?? other) : null,
        amount: num(r.amount) ?? (entries.length ? entries.reduce((s, e) => s + entryDebit(e), 0) : null),
        currency: companyCurrency(idx, pair[0]),
        date: idx.monthEnd,
        status: adjusted ? 'AUTO' : 'OPEN',
        outcome: cause,
        reasons: [],
        policyRefs: refs(entry ?? '§6'),
        evidence: [{ kind: 'erp', file: 'erp/intercompany_agreements.json', key: IC_EVIDENCE_KEY[cause] ?? 'loan' }],
        rowIndex,
      },
      entries,
    )
  })
}

// ---------------------------------------------------------------- close
function closeItems(c: Ctx, rows: CloseRow[]) {
  const { idx } = c
  const groups = new Map<ItemId, { rows: CloseRow[]; first: number }>()
  rows.forEach((r, i) => {
    const id = closeItemId(...closeKeyParts(r))
    const g = groups.get(id)
    if (g) g.rows.push(r)
    else groups.set(id, { rows: [r], first: i })
  })
  for (const [id, g] of groups) {
    const r = g.rows[0]
    const type = String(r.type)
    const keyValue = (r as Record<string, unknown>)[closeKeyField(type)]
    const vendor = r.vendor ? idx.vendors.get(r.vendor) : undefined
    const customer = r.customer ? idx.customers.get(r.customer) : undefined
    const counterparty = vendor?.name ?? customer?.name ?? null
    const entries = g.rows.flatMap((x) => rowJournal('close', x))
    const evidence: EvidenceRef[] = [...vendorRef(r.vendor), ...customerRef(r.customer)]
    for (const x of g.rows) if (x.invoice) evidence.push({ kind: 'erp', file: 'erp/ap_invoices.jsonl', key: x.invoice })
    if (typeof r.item === 'string' && r.item.startsWith('AP:')) evidence.push({ kind: 'erp', file: 'erp/ap_invoices.jsonl', key: r.item.slice(3) })
    if (r.billing_item) for (const path of idx.billingInbox.get(r.billing_item)?.files ?? []) evidence.push({ kind: 'doc', path })
    const entry = CLOSE_TYPE_CATALOG[type as keyof typeof CLOSE_TYPE_CATALOG]
    push(
      c,
      {
        id,
        task: 'close',
        key: id.slice('close:'.length),
        company: str(r.company),
        title: `${entry?.label ?? type} · ${counterparty ?? String(keyValue ?? r.company)}`,
        counterparty,
        amount: g.rows.reduce((s, x) => s + (num(x.amount) ?? 0), 0),
        currency: companyCurrency(idx, r.company),
        date: str(r.journal_entry?.posting_date) ?? idx.monthEnd,
        status: 'AUTO',
        outcome: type,
        reasons: [],
        policyRefs: refs(entry ?? '§5'),
        evidence: uniqEvidence(evidence),
        rowIndex: g.first,
      },
      entries,
    )
  }
}

const uniqEvidence = (xs: EvidenceRef[]): EvidenceRef[] => {
  const seen = new Set<string>()
  return xs.filter((x) => {
    const k = JSON.stringify(x)
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

// ---------------------------------------------------------------- entry point
const cache = new WeakMap<DatasetCore, WeakMap<RunBundle, BuiltItems>>()

/** Items and their entries for a run (absent files contribute nothing). Cached per (core, run). */
export function buildItems(core: DatasetCore, run: RunBundle): BuiltItems {
  let perCore = cache.get(core)
  if (!perCore) cache.set(core, (perCore = new WeakMap()))
  const hit = perCore.get(run)
  if (hit) return hit
  const d = effectiveDeliverables(run)
  const eventsByItem = groupEvents(run.events ?? [])
  const c: Ctx = { idx: coreIndex(core), run, eventsByItem, items: [], entries: new Map() }
  apItems(c, d.ap)
  arBillingItems(c, d.ar_billing)
  arCashItems(c, d.ar_cash)
  bankItems(c, d.bank_rec)
  icItems(c, d.ic)
  closeItems(c, d.close)
  const built = { items: c.items, entries: c.entries }
  perCore.set(run, built)
  return built
}

export function groupEvents(events: readonly AgentEvent[]): Map<ItemId, AgentEvent[]> {
  const m = new Map<ItemId, AgentEvent[]>()
  for (const e of events) {
    const list = m.get(e.item)
    if (list) list.push(e)
    else m.set(e.item, [e])
  }
  for (const list of m.values()) list.sort((a, b) => a.seq - b.seq)
  return m
}

/** WorkItems of a run per PLAN §5 (statuses before attention is applied). */
export const deriveItems = (core: DatasetCore, run: RunBundle): WorkItem[] => buildItems(core, run).items

/** Journal entries behind one item (what its «Asiento» tab shows). */
export const itemEntries = (core: DatasetCore, run: RunBundle, itemId: ItemId): JournalEntryOut[] =>
  buildItems(core, run).entries.get(itemId) ?? []
