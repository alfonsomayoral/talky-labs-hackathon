// Pure helpers behind the overview: task metadata, EUR normalisation, outcome breakdowns,
// score facts and the close controls (555, banks, intercompany, validation).

import type {
  AttentionItem,
  BankCategory,
  BankRecRow,
  Company,
  FxRate,
  ItemId,
  RunSource,
  TaskKey,
  TbRow,
  TrialBalanceComparison,
  ValidationReport,
  WorkItem,
} from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { BANK_CATEGORY_CATALOG, outcomeEntry } from '@/domain/catalog/policy'
import { ITEM_STATUS_ORDER } from '@/components'
import { formatMoney, formatPercent } from '@/lib/format'

// ---------------------------------------------------------------- tasks and runs

/** Execution order of the close: AP feeds banks, cash and close; close goes last. */
export const PIPELINE: readonly TaskKey[] = ['ap', 'ar_billing', 'bank_rec', 'ar_cash', 'ic', 'close']

export const TASK_META: Record<TaskKey, { label: string; route: string }> = {
  ap: { label: 'Bandeja AP', route: '/tareas/ap' },
  ar_billing: { label: 'Facturación', route: '/tareas/facturacion' },
  bank_rec: { label: 'Bancos', route: '/tareas/bancos' },
  ar_cash: { label: 'Cobros', route: '/tareas/cobros' },
  ic: { label: 'Intragrupo', route: '/tareas/intragrupo' },
  close: { label: 'Cierre', route: '/tareas/cierre' },
}

export const RUN_SOURCE_LABEL: Record<RunSource, string> = {
  golden: 'Referencia (golden)',
  import: 'Importada',
  api: 'Backend',
}

const MONTH_LONG = new Intl.DateTimeFormat('es-ES', { month: 'long', year: 'numeric', timeZone: 'UTC' })

/** `2026-07` → `julio de 2026`. */
export function longMonth(month: string): string {
  const d = new Date(`${month.slice(0, 7)}-01T00:00:00Z`)
  return Number.isNaN(d.getTime()) ? month : MONTH_LONG.format(d)
}

// ---------------------------------------------------------------- EUR normalisation

/** Company-currency cents → EUR cents. NaN when the company's currency has no rate. */
export type ToEur = (company: string | null, cents: number) => number

/** Converts at the last SYN-BCE rate on or before the month end (rates are units per EUR). Unknown companies count as EUR. */
export function eurConverter(companies: readonly Company[], fxRates: readonly FxRate[], month: string): ToEur {
  const monthEnd = `${month.slice(0, 7)}-31`
  const latest = new Map<string, FxRate>()
  for (const r of fxRates) {
    if (r.base !== 'EUR' || r.date > monthEnd) continue
    const prev = latest.get(r.currency)
    if (!prev || r.date > prev.date) latest.set(r.currency, r)
  }
  const rateOf = new Map(companies.map((c) => [c.code, c.currency === 'EUR' ? 1 : (latest.get(c.currency)?.rate ?? Number.NaN)]))
  return (company, cents) => cents / (rateOf.get(company ?? '') ?? 1)
}

// ---------------------------------------------------------------- attention and balance

export interface AttentionSummary {
  count: number
  impactEur: number
  byTask: Record<TaskKey, number>
}

export function attentionSummary(attention: readonly AttentionItem[], itemsById: ReadonlyMap<ItemId, WorkItem>, toEur: ToEur): AttentionSummary {
  const byTask = Object.fromEntries(TASK_KEYS.map((k) => [k, 0])) as Record<TaskKey, number>
  let impactEur = 0
  for (const a of attention) {
    const item = itemsById.get(a.item)
    const task = item?.task ?? (a.item.slice(0, a.item.indexOf(':')) as TaskKey)
    if (task in byTask) byTask[task]++
    impactEur += toEur(item?.company ?? null, a.impact)
  }
  return { count: attention.length, impactEur, byTask }
}

export interface BalanceSummary {
  /** Share of the recorded → truth gap closed, as score.py (null without golden). */
  score: number | null
  gapRecordedEur: number | null
  gapAfterEur: number | null
  /** Σ|movement| per task in EUR, largest first. */
  movement: { task: TaskKey; amountEur: number }[]
}

export function balanceSummary(tb: TrialBalanceComparison, toEur: ToEur): BalanceSummary {
  const movement = Object.fromEntries(TASK_KEYS.map((k) => [k, 0])) as Record<TaskKey, number>
  let gapRecorded = 0
  let gapAfter = 0
  for (const r of tb.rows) {
    for (const task of TASK_KEYS) movement[task] += Math.abs(toEur(r.company, r.delta[task] ?? 0))
    if (r.truth !== null) {
      gapRecorded += Math.abs(toEur(r.company, r.truth - r.recorded))
      gapAfter += Math.abs(toEur(r.company, r.truth - r.after))
    }
  }
  const known = tb.score !== null
  return {
    score: tb.score,
    gapRecordedEur: known ? gapRecorded : null,
    gapAfterEur: known ? gapAfter : null,
    movement: TASK_KEYS.map((task) => ({ task, amountEur: movement[task] })).sort((a, b) => b.amountEur - a.amountEur),
  }
}

// ---------------------------------------------------------------- outcomes and scores

export interface OutcomeCount {
  outcome: string
  label: string
  count: number
}

/** Items of one task by outcome (decision, category, type), most frequent first. */
export function outcomeBreakdown(items: readonly WorkItem[], task: TaskKey): OutcomeCount[] {
  const counts = new Map<string, number>()
  for (const it of items) if (it.task === task) counts.set(it.outcome, (counts.get(it.outcome) ?? 0) + 1)
  return [...counts]
    .map(([outcome, count]) => ({ outcome, label: outcomeEntry(task, outcome)?.label ?? outcome, count }))
    .sort((a, b) => b.count - a.count || (a.outcome < b.outcome ? -1 : 1))
}

export interface ScoreFact {
  label: string
  value: string
}

const AP_PARTS: [string, string][] = [
  ['decision_macro_f1', 'Decisión (F1)'],
  ['header', 'Cabecera'],
  ['coding', 'Imputación'],
  ['po_match', 'Pedido'],
  ['journal_entry', 'Asiento'],
  ['reasons', 'Motivos'],
  ['payee_and_block', 'Beneficiario y bloqueo'],
]

const n = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) ? v : 0)
const of = (part: unknown, whole: unknown) => `${n(part)} de ${n(whole)}`

/** Sub-scores of a task as score.py reports them in `details`. */
export function scoreFacts(task: TaskKey, details: Record<string, unknown>): ScoreFact[] {
  switch (task) {
    case 'ap':
      return AP_PARTS.filter(([k]) => k in details).map(([k, label]) => ({ label, value: formatPercent(n(details[k])) }))
    case 'ar_billing':
      return [{ label: 'Respondidas', value: of(details.answered, details.items) }]
    case 'ar_cash':
      return [{ label: 'Cobros exactos', value: of(details.fully_correct, details.receipts) }]
    case 'bank_rec': {
      const perAccount = Object.values((details.per_account ?? {}) as Record<string, number>)
      return [{ label: 'Cuentas al 100 %', value: of(perAccount.filter((s) => s >= 1).length, perAccount.length) }]
    }
    case 'ic':
      return [{ label: 'Diferencias detectadas', value: of(details.detected, details.differences) }]
    case 'close':
      return [
        { label: 'Exhaustividad', value: formatPercent(n(details.recall)) },
        { label: 'Precisión', value: formatPercent(n(details.precision)) },
      ]
  }
}

// ---------------------------------------------------------------- mosaic

const STATUS_RANK = new Map(ITEM_STATUS_ORDER.map((s, i) => [s, i]))

/** Items grouped by task in pipeline order; inside each task by status (canonical order), then file order. */
export function mosaicRows(items: readonly WorkItem[]): { task: TaskKey; items: WorkItem[] }[] {
  return PIPELINE.map((task) => ({
    task,
    items: items
      .filter((it) => it.task === task)
      .sort((a, b) => (STATUS_RANK.get(a.status) ?? 9) - (STATUS_RANK.get(b.status) ?? 9) || a.rowIndex - b.rowIndex),
  }))
}

// ---------------------------------------------------------------- close controls

export type ControlTone = 'ok' | 'warn' | 'danger'

export const PENDING_ACCOUNT = '55500000'

export interface Pending555 {
  tone: ControlTone
  recordedEur: number
  afterEur: number
  /** Companies still carrying a balance after the run, in their own currency. */
  remaining: { company: string; after: number }[]
}

/** 55500000 «cobros pendientes de aplicar» must end at zero in every company. */
export function pending555(rows: readonly TbRow[], toEur: ToEur): Pending555 {
  let recordedEur = 0
  let afterEur = 0
  const remaining: Pending555['remaining'] = []
  for (const r of rows) {
    if (r.account !== PENDING_ACCOUNT) continue
    recordedEur += toEur(r.company, r.recorded)
    afterEur += toEur(r.company, r.after)
    if (r.after !== 0) remaining.push({ company: r.company, after: r.after })
  }
  return { tone: remaining.length ? 'warn' : 'ok', recordedEur, afterEur, remaining }
}

export interface BanksControl {
  tone: ControlTone
  total: number
  reconciled: number
  /** Accounts in tasks/ without a row in bank_rec. */
  missing: string[]
  /** Accounts with an open difference that needs an adjustment the delivery lacks. */
  unexplained: string[]
  /** Open differences that need no adjustment (outstanding payments, transfers in transit, prior period…). */
  reconcilingItems: number
}

/**
 * An account is reconciled when it is delivered and every open difference is either a category
 * that needs no adjustment or one whose adjustment the delivery books in the same company
 * (a wrong-account payment is adjusted once, on one of the two accounts).
 */
export function banksControl(expected: readonly string[], rows: readonly BankRecRow[], items: readonly WorkItem[]): BanksControl {
  const accounts = expected.length ? expected : rows.map((r) => String(r.account))
  const delivered = new Set(rows.map((r) => String(r.account)))
  const adjusted = new Set(rows.flatMap((r) => (Array.isArray(r.adjustments) ? r.adjustments : []).map((a) => `${r.company}|${a.category}`)))
  const unexplained = new Set<string>()
  let reconcilingItems = 0
  for (const it of items) {
    if (it.task !== 'bank_rec' || it.status !== 'OPEN') continue
    const entry = BANK_CATEGORY_CATALOG[it.outcome as BankCategory]
    if (entry && (!entry.adjustment || adjusted.has(`${it.company}|${it.outcome}`))) reconcilingItems++
    else unexplained.add(it.key.slice(0, it.key.indexOf('/')))
  }
  const missing = accounts.filter((a) => !delivered.has(a))
  const reconciled = accounts.filter((a) => delivered.has(a) && !unexplained.has(a)).length
  return {
    tone: missing.length ? 'danger' : unexplained.size ? 'warn' : 'ok',
    total: accounts.length,
    reconciled,
    missing,
    unexplained: [...unexplained],
    reconcilingItems,
  }
}

export const IC_PAIRS = [
  { id: 'invoices', label: 'Facturas', accounts: ['43300000', '40300000'] },
  { id: 'pooling', label: 'Cash pooling', accounts: ['55200000'] },
  { id: 'loan', label: 'Préstamo KMI', accounts: ['24230000', '16330000'] },
  { id: 'ute', label: 'UTE', accounts: ['55210000', '55220000'] },
] as const

export interface IcPairNet {
  id: string
  label: string
  accounts: readonly string[]
  recordedEur: number
  afterEur: number
  /** Net of the correct balance (null without golden). */
  truthEur: number | null
  tone: ControlTone
}

/** Off by at most 1 € (FX conversion rounding). */
export const IC_TOLERANCE_CENTS = 100

/**
 * Net balance of each intercompany account pair across companies, in EUR. With golden the
 * after-run net must equal the correct net (the invoice and UTE pairs do not net to zero in the
 * data); without golden it must be zero.
 */
export function intercompanyControl(rows: readonly TbRow[], toEur: ToEur): { tone: ControlTone; pairs: IcPairNet[] } {
  const pairs = IC_PAIRS.map((p): IcPairNet => {
    let recordedEur = 0
    let afterEur = 0
    let truthEur: number | null = null
    for (const r of rows) {
      if (!(p.accounts as readonly string[]).includes(r.account)) continue
      recordedEur += toEur(r.company, r.recorded)
      afterEur += toEur(r.company, r.after)
      if (r.truth !== null) truthEur = (truthEur ?? 0) + toEur(r.company, r.truth)
    }
    const ok = Math.abs(afterEur - (truthEur ?? 0)) <= IC_TOLERANCE_CENTS
    return { id: p.id, label: p.label, accounts: p.accounts, recordedEur, afterEur, truthEur, tone: ok ? 'ok' : 'warn' }
  })
  return { tone: pairs.every((p) => p.tone === 'ok') ? 'ok' : 'warn', pairs }
}

export interface DeliveryControl {
  tone: ControlTone
  errors: number
  warnings: number
  missingFiles: TaskKey[]
}

export function deliveryControl(validation: ValidationReport): DeliveryControl {
  const files = TASK_KEYS.map((k) => validation.files[k])
  return {
    tone: validation.ok ? 'ok' : 'danger',
    errors: files.reduce((s, f) => s + f.errors.length, 0),
    warnings: files.reduce((s, f) => s + f.warnings.length, 0),
    missingFiles: files.filter((f) => !f.present).map((f) => f.task),
  }
}

/** `1,2 M€` from EUR cents (NaN → «—»). */
export const eur = (cents: number | null): string => formatMoney(cents, 'EUR', { compact: true })
