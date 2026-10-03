// Format validation of the six deliverables against tasks/ and FORMATO_ENTREGA.md (CONTRACT.md §3).

import type { DatasetCore, FileValidation, RunBundle, TaskKey, ValidationReport } from '@/domain/types'
import {
  AP_ACTIONS,
  AP_DECISIONS,
  AP_DOCUMENT_TYPES,
  AP_REASONS,
  AR_RESIDUAL_TYPES,
  BANK_CATEGORIES,
  CLOSE_TYPES,
  DELIVERABLE_FILES,
  IC_CAUSES,
  TASK_KEYS,
} from '@/domain/types'
import { rowKey } from '../ids'
import { asJournalEntry, entryImbalance, rowEntries } from '../ledger/entries'
import { get, isDict, pyIter } from '../score/py'

const DATE = /^\d{4}-\d{2}-\d{2}$/

function expectedKeys(core: DatasetCore, task: TaskKey): string[] | null {
  const t = core.tasks
  switch (task) {
    case 'ap':
      return t.ap_documents
    case 'ar_billing':
      return t.ar_billing_items
    case 'ar_cash':
      return t.ar_receipts
    case 'bank_rec':
      return t.bank_accounts
    default:
      return null
  }
}

interface Ctx {
  v: FileValidation
  key: string
  chart: Set<string>
  accounts: Set<string>
}

function enumValue(c: Ctx, field: string, value: unknown, allowed: readonly string[], nullable = false) {
  if (nullable && (value === null || value === undefined)) return
  if (typeof value !== 'string' || !allowed.includes(value)) c.v.invalidValues.push({ key: c.key, field, value: value ?? null })
}

function dateValue(c: Ctx, field: string, value: unknown, nullable = true) {
  if (nullable && (value === null || value === undefined)) return
  if (typeof value !== 'string' || !DATE.test(value)) c.v.invalidValues.push({ key: c.key, field, value: value ?? null })
}

function amount(c: Ctx, value: unknown, nullable = false) {
  if (nullable && (value === null || value === undefined)) return
  if (typeof value !== 'number' || !Number.isInteger(value)) c.v.nonIntegerAmounts++
}

function account(c: Ctx, value: unknown) {
  if (value === null || value === undefined) return
  const a = String(value)
  if (!c.chart.has(a)) c.accounts.add(a)
}

function entries(c: Ctx, task: TaskKey, row: unknown) {
  rowEntries(task, row).forEach((e, i) => {
    const je = asJournalEntry(e)
    for (const l of je.lines) {
      if (!isDict(l)) continue
      amount(c, l.debit, true)
      amount(c, l.credit, true)
      account(c, l.account)
    }
    if (entryImbalance(je).size) c.v.unbalancedEntries.push(task === 'bank_rec' ? `${c.key}/adjustments[${i}]` : c.key)
  })
}

function checkAp(c: Ctx, r: unknown) {
  enumValue(c, 'document_type', get(r, 'document_type'), AP_DOCUMENT_TYPES)
  enumValue(c, 'decision', get(r, 'decision'), AP_DECISIONS)
  for (const reason of pyIter(get(r, 'reasons'))) enumValue(c, 'reasons', reason, AP_REASONS)
  enumValue(c, 'action', get(r, 'action'), AP_ACTIONS, true)
  const payee = get(r, 'payee')
  if (payee !== null) enumValue(c, 'payee.type', get(payee, 'type'), ['FACTOR', 'AEAT_EMBARGO'])
  enumValue(c, 'payment_block', get(r, 'payment_block'), ['CONTRACTOR_CERTIFICATE_EXPIRED'], true)
  dateValue(c, 'invoice_date', get(r, 'invoice_date'))
  for (const k of ['net', 'tax', 'gross', 'withholding', 'retention', 'payable']) amount(c, get(r, k), true)
  for (const l of pyIter(get(r, 'lines'))) {
    amount(c, get(l, 'amount'))
    account(c, get(l, 'account'))
  }
  const decision = get(r, 'decision')
  const posts = decision === 'POST' || decision === 'POST_PAYMENT_BLOCK'
  if (posts && !get(r, 'journal_entry')) c.v.warnings.push(`${c.key}: ${String(decision)} sin asiento`)
  if (!posts && get(r, 'journal_entry')) c.v.warnings.push(`${c.key}: lleva asiento con decisión ${String(decision)}`)
  if (decision === 'NOT_INVOICE' && !get(r, 'action')) c.v.warnings.push(`${c.key}: NOT_INVOICE sin acción`)
  if (decision === 'DUPLICATE' && !get(r, 'duplicate_of')) c.v.warnings.push(`${c.key}: DUPLICATE sin duplicate_of`)
  if ((decision === 'HOLD' || decision === 'REJECT') && !pyIter(get(r, 'reasons')).length) c.v.warnings.push(`${c.key}: ${decision} sin motivo`)
}

function checkArBilling(c: Ctx, r: unknown) {
  enumValue(c, 'expected', get(r, 'expected'), ['INVOICE', 'SKIP_PENDING_APPROVAL'])
  const inv = get(r, 'invoice')
  if (get(r, 'expected') === 'INVOICE' && !inv) c.v.warnings.push(`${c.key}: INVOICE sin factura`)
  if (!inv) return
  dateValue(c, 'invoice.date', get(inv, 'date'), false)
  dateValue(c, 'invoice.due_date', get(inv, 'due_date'), false)
  for (const k of ['net', 'tax', 'retention', 'payable']) amount(c, get(inv, k))
  for (const d of pyIter(get(inv, 'deductions'))) {
    amount(c, get(d, 'amount'))
    account(c, get(d, 'account'))
  }
  for (const l of pyIter(get(inv, 'lines'))) {
    amount(c, get(l, 'amount'))
    account(c, get(l, 'account'))
  }
}

function checkArCash(c: Ctx, r: unknown) {
  for (const a of pyIter(get(r, 'applications'))) amount(c, get(a, 'amount'))
  for (const x of pyIter(get(r, 'residuals'))) {
    enumValue(c, 'residuals.type', get(x, 'type'), AR_RESIDUAL_TYPES)
    amount(c, get(x, 'amount'))
    account(c, get(x, 'account'))
  }
}

function checkBank(c: Ctx, r: unknown) {
  for (const m of pyIter(get(r, 'matches'))) enumValue(c, 'matches.category', get(m, 'category'), [...BANK_CATEGORIES, 'MATCH'], true)
  for (const x of pyIter(get(r, 'unmatched_bank'))) enumValue(c, 'unmatched_bank.category', get(x, 'category'), BANK_CATEGORIES)
  for (const x of pyIter(get(r, 'unmatched_book'))) enumValue(c, 'unmatched_book.category', get(x, 'category'), BANK_CATEGORIES)
  for (const a of pyIter(get(r, 'adjustments'))) enumValue(c, 'adjustments.category', get(a, 'category'), BANK_CATEGORIES)
}

function checkIc(c: Ctx, r: unknown, companies: Set<string>) {
  enumValue(c, 'cause', get(r, 'cause'), IC_CAUSES)
  const pair = pyIter(get(r, 'pair'))
  if (pair.length !== 2 || !pair.every((x) => companies.has(String(x)))) c.v.invalidValues.push({ key: c.key, field: 'pair', value: get(r, 'pair') })
  amount(c, get(r, 'amount'), true)
}

function checkClose(c: Ctx, r: unknown) {
  enumValue(c, 'type', get(r, 'type'), CLOSE_TYPES)
  amount(c, get(r, 'amount'))
}

function validateFile(core: DatasetCore, run: Pick<RunBundle, 'deliverables' | 'present'>, task: TaskKey): FileValidation {
  const present = run.present?.[task] !== false
  const rows: unknown[] = present ? (run.deliverables[task] ?? []) : []
  const expected = expectedKeys(core, task)
  const v: FileValidation = {
    task,
    present,
    rows: rows.length,
    expected: expected ? expected.length : null,
    missingKeys: [],
    duplicateKeys: [],
    extraKeys: [],
    unbalancedEntries: [],
    nonIntegerAmounts: 0,
    unknownAccounts: [],
    invalidValues: [],
    errors: [],
    warnings: [],
  }
  const file = DELIVERABLE_FILES[task]
  if (!present) {
    v.missingKeys = expected ? [...expected] : []
    v.errors.push(`Falta el fichero ${file}`)
    return v
  }
  const chart = new Set(core.chartOfAccounts.map((a) => a.account))
  const companies = new Set(core.companies.map((x) => x.code))
  const accounts = new Set<string>()
  const seen = new Set<string>()
  const dup = new Set<string>()
  for (const r of rows) {
    const key = rowKey(task, r)
    // Several close rows may share a key (two accruals of one vendor): score.py adds them up.
    if (seen.has(key) && task !== 'close') dup.add(key)
    seen.add(key)
    const c: Ctx = { v, key, chart, accounts }
    if (task === 'ap') checkAp(c, r)
    else if (task === 'ar_billing') checkArBilling(c, r)
    else if (task === 'ar_cash') checkArCash(c, r)
    else if (task === 'bank_rec') checkBank(c, r)
    else if (task === 'ic') checkIc(c, r, companies)
    else checkClose(c, r)
    entries(c, task, r)
  }
  v.duplicateKeys = [...dup]
  v.unknownAccounts = [...accounts].sort()
  if (expected) {
    const want = new Set(expected)
    v.missingKeys = expected.filter((k) => !seen.has(k))
    v.extraKeys = [...seen].filter((k) => !want.has(k))
  }
  if (v.missingKeys.length) v.errors.push(`${v.missingKeys.length} elementos de tasks/ sin fila`)
  if (v.extraKeys.length) v.errors.push(`${v.extraKeys.length} filas que no están en tasks/`)
  if (v.duplicateKeys.length) v.errors.push(`${v.duplicateKeys.length} claves duplicadas`)
  if (v.unbalancedEntries.length) v.errors.push(`${v.unbalancedEntries.length} asientos descuadrados`)
  if (v.nonIntegerAmounts) v.errors.push(`${v.nonIntegerAmounts} importes que no son céntimos enteros`)
  if (v.unknownAccounts.length) v.errors.push(`${v.unknownAccounts.length} cuentas fuera del plan`)
  if (v.invalidValues.length) v.errors.push(`${v.invalidValues.length} valores no permitidos`)
  return v
}

export function validateDeliverables(core: DatasetCore, run: Pick<RunBundle, 'deliverables' | 'present'>): ValidationReport {
  const files = Object.fromEntries(TASK_KEYS.map((k) => [k, validateFile(core, run, k)])) as Record<TaskKey, FileValidation>
  return { ok: TASK_KEYS.every((k) => files[k].errors.length === 0), files }
}
