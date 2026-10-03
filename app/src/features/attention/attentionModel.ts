// Pure helpers of the Attention queue: families, grouping, filters, similar items and labels.

import type { AttentionItem, AttentionKind, ItemId, Priority, TaskKey, WorkItem } from '@/domain/types'
import {
  AP_DECISION_CATALOG,
  AR_BILLING_OUTCOME_CATALOG,
  AR_CASH_OUTCOME_CATALOG,
  BANK_CATEGORY_CATALOG,
  IC_CAUSE_CATALOG,
  outcomeEntry,
  reasonEntry,
  type PolicyEntry,
} from '@/domain/catalog/policy'
import { KIND_LABEL } from '@/domain/catalog/labels'
import { parseItemId, sortAttention } from '@/engine'
import type { Override } from './overridesStore'

/** fraud goes first and alone; world = the agent is sure but someone must act outside; doubt = the agent is unsure. */
export type Family = 'fraud' | 'world' | 'doubt'

const KIND_FAMILY: Record<AttentionKind, Family> = {
  FRAUD_SIGNAL: 'fraud',
  POLICY_EXCEPTION: 'world',
  MASTER_DATA: 'world',
  CROSS_TASK: 'world',
  AGENT_DOUBT: 'doubt',
  ESTIMATE: 'doubt',
  MATERIAL_UNEXPLAINED: 'doubt',
  DATA_QUALITY: 'doubt',
}

export const familyOf = (kind: AttentionKind): Family => KIND_FAMILY[kind] ?? 'doubt'

export const kindLabel = (kind: AttentionKind): string => KIND_LABEL[kind] ?? kind

export const PRIORITIES: Priority[] = ['P0', 'P1', 'P2', 'P3']

export type Resolution = 'pending' | 'snoozed' | 'resolved'

export interface AttentionRow {
  /** Stable React/selection key. */
  key: string
  a: AttentionItem
  task: TaskKey | null
  item: WorkItem | null
  family: Family
  override: Override | null
  resolution: Resolution
}

/** The item key without its task prefix (API004151, BIN-1100/BL0000706). */
export const rowKeyLabel = (r: AttentionRow): string => r.item?.key ?? r.a.item.slice(r.a.item.indexOf(':') + 1)

/** attention_id as stored in overrides ('' from a backend becomes null). */
export const attentionIdOf = (a: AttentionItem): string | null => a.attention_id || null

/** The override of this entry: same item and attention_id; an item-wide override (attention_id null) as fallback. */
export function overrideFor(overrides: readonly Override[], a: AttentionItem): Override | null {
  const id = attentionIdOf(a)
  let itemWide: Override | null = null
  for (const o of overrides) {
    if (o.item !== a.item) continue
    if (o.attention_id === id) return o
    if (o.attention_id == null) itemWide = o
  }
  return itemWide
}

export function resolutionOf(o: Override | null): Resolution {
  if (!o || o.action === 'NOTE') return 'pending'
  return o.action === 'SNOOZE' ? 'snoozed' : 'resolved'
}

/** Rows in queue order: priority, then expected loss ((1 − p) × impact, or impact). */
export function buildRows(attention: readonly AttentionItem[], itemsById: ReadonlyMap<ItemId, WorkItem>, overrides: readonly Override[]): AttentionRow[] {
  const byItem = new Map<string, Override[]>()
  for (const o of overrides) byItem.set(o.item, [...(byItem.get(o.item) ?? []), o])
  return sortAttention([...attention]).map((a, i) => {
    const item = itemsById.get(a.item) ?? null
    const override = overrideFor(byItem.get(a.item) ?? [], a)
    return {
      key: a.attention_id || `${a.item}#${a.kind}#${i}`,
      a,
      task: item?.task ?? parseItemId(a.item)?.task ?? null,
      item,
      family: familyOf(a.kind),
      override,
      resolution: resolutionOf(override),
    }
  })
}

export interface CurrencyTotal {
  currency: string
  cents: number
}

/** Impacts are in each company's currency (MXN in 3100), so they are summed per currency, EUR first. */
export function totalsByCurrency(rows: readonly AttentionRow[]): CurrencyTotal[] {
  const sums = new Map<string, number>()
  for (const r of rows) {
    const currency = r.item?.currency ?? 'EUR'
    sums.set(currency, (sums.get(currency) ?? 0) + r.a.impact)
  }
  return [...sums]
    .map(([currency, cents]) => ({ currency, cents }))
    .sort((x, y) => (x.currency === 'EUR' ? -1 : y.currency === 'EUR' ? 1 : x.currency.localeCompare(y.currency)))
}

export interface PriorityGroup {
  priority: Priority
  rows: AttentionRow[]
  totals: CurrencyTotal[]
}

/** P0 → P3, skipping empty priorities; rows keep their incoming order. */
export function groupByPriority(rows: readonly AttentionRow[]): PriorityGroup[] {
  return PRIORITIES.map((priority) => {
    const inGroup = rows.filter((r) => r.a.priority === priority)
    return { priority, rows: inGroup, totals: totalsByCurrency(inGroup) }
  }).filter((g) => g.rows.length > 0)
}

export interface AttentionFilters {
  priority: string[]
  kind: string[]
  task: string[]
  company: string[]
  query: string
}

export const NO_FILTERS: AttentionFilters = { priority: [], kind: [], task: [], company: [], query: '' }

export const hasFilters = (f: AttentionFilters): boolean =>
  f.priority.length + f.kind.length + f.task.length + f.company.length > 0 || f.query.trim() !== ''

const normalize = (s: string) =>
  s
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()

const facet = (selected: string[], value: string | null | undefined) => selected.length === 0 || (value != null && selected.includes(value))

export function matchesFilters(r: AttentionRow, f: AttentionFilters): boolean {
  if (!facet(f.priority, r.a.priority) || !facet(f.kind, r.a.kind) || !facet(f.task, r.task) || !facet(f.company, r.item?.company)) return false
  const q = normalize(f.query.trim())
  if (!q) return true
  const haystack = [r.a.title, r.a.item, r.item?.counterparty, kindLabel(r.a.kind), r.a.suggested_action].filter(Boolean).join(' ')
  return normalize(haystack).includes(q)
}

const signature = (r: AttentionRow): string | null => {
  const decision = r.a.recommendation?.decision
  if (!decision || !r.task) return null
  const reasons = [...(r.a.recommendation?.reasons ?? [])].sort().join(',')
  return [r.task, r.a.kind, decision, reasons].join('|')
}

/** Other pending rows with the same task, kind and recommendation (decision + reasons). */
export function similarRows(target: AttentionRow, rows: readonly AttentionRow[]): AttentionRow[] {
  const sig = signature(target)
  if (!sig) return []
  return rows.filter((r) => r.key !== target.key && r.resolution === 'pending' && signature(r) === sig)
}

export function decisionLabel(task: TaskKey | null, code: string): string {
  return (task && outcomeEntry(task, code)?.label) || code
}

export function reasonLabel(task: TaskKey | null, code: string): string {
  return (task && reasonEntry(task, code)?.label) || code
}

const DECISION_CATALOGS: Partial<Record<TaskKey, Record<string, PolicyEntry>>> = {
  ap: AP_DECISION_CATALOG,
  ar_billing: AR_BILLING_OUTCOME_CATALOG,
  ar_cash: AR_CASH_OUTCOME_CATALOG,
  bank_rec: BANK_CATEGORY_CATALOG,
  ic: IC_CAUSE_CATALOG,
}

export interface DecisionOption {
  decision: string
  label: string
  /** Probability from the agent's alternatives, when it gave one. */
  p: number | null
}

/** Choices for «Elegir alternativa»: the agent's alternatives (by p) and the task's other decisions. */
export function decisionOptions(r: AttentionRow): { alternatives: DecisionOption[]; others: DecisionOption[] } {
  const recommended = r.a.recommendation?.decision
  const alternatives = [...(r.a.alternatives ?? [])]
    .filter((x) => x.decision !== recommended)
    .sort((x, y) => y.p - x.p)
    .map((x) => ({ decision: x.decision, label: decisionLabel(r.task, x.decision), p: x.p }))
  const taken = new Set([recommended, ...alternatives.map((x) => x.decision)])
  const catalog = r.task ? (DECISION_CATALOGS[r.task] ?? {}) : {}
  const others = Object.entries(catalog)
    .filter(([code]) => !taken.has(code))
    .map(([code, e]) => ({ decision: code, label: e.label, p: null }))
  return { alternatives, others }
}

/** Description of the policy section cited, from the catalog entries of the recommendation. */
export function policyDescription(r: AttentionRow): string | null {
  const ref = r.a.policy_ref
  if (!ref || !r.task) return null
  const task = r.task
  const rec = r.a.recommendation
  const entries = [...(rec?.reasons ?? []).map((c) => reasonEntry(task, c)), rec?.decision ? outcomeEntry(task, rec.decision) : null].filter(
    (e): e is PolicyEntry => !!e,
  )
  const hit = entries.find((e) => e.section === ref) ?? entries.find((e) => e.section.startsWith(ref) || ref.startsWith(e.section))
  return hit?.description ?? null
}
