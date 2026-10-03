// Pure helpers behind /balance: the gap closed task by task, the company × account-group heat map and row differences.

import type { Cents, TaskKey, TbRow, TrialBalanceComparison } from '@/domain/types'
import { PIPELINE } from '@/domain/catalog/labels'
import type { ToEur } from '@/engine'

// ---------------------------------------------------------------- waterfall

export interface GapStep {
  task: TaskKey
  /** EUR cents of gap this task closes once the previous ones are applied (negative: it opens gap). */
  closed: Cents
  /** Gap left after this task and the previous ones. */
  remaining: Cents
}

export interface GapWaterfall {
  recorded: Cents
  steps: GapStep[]
  after: Cents
}

/**
 * Σ|truth − balance| in EUR, adding the tasks one by one in pipeline order. The gap is not additive
 * (one task's entry can only square once another has posted), so each step depends on the order;
 * the steps always add up to recorded − after. Null without golden.
 */
export function gapWaterfall(tb: TrialBalanceComparison, toEur: ToEur, order: readonly TaskKey[] = PIPELINE): GapWaterfall | null {
  if (tb.gapRecorded === null) return null
  const balances = tb.rows.map((r) => r.recorded)
  const gap = () => tb.rows.reduce((s, r, i) => s + Math.abs(toEur(r.company, (r.truth ?? 0) - balances[i])), 0)
  const recorded = gap()
  let previous = recorded
  const steps = order.map((task) => {
    tb.rows.forEach((r, i) => (balances[i] += r.delta[task] ?? 0))
    const remaining = gap()
    const step = { task, closed: previous - remaining, remaining }
    previous = remaining
    return step
  })
  return { recorded, steps, after: previous }
}

// ---------------------------------------------------------------- heat map

export const ACCOUNT_GROUPS = ['1', '2', '3', '4', '5', '6', '7'] as const

export const ACCOUNT_GROUP_LABEL: Record<string, string> = {
  '1': 'Financiación básica',
  '2': 'Inmovilizado',
  '3': 'Existencias',
  '4': 'Acreedores y deudores',
  '5': 'Cuentas financieras',
  '6': 'Gastos',
  '7': 'Ingresos',
}

export const accountGroup = (account: string) => account.charAt(0)

export type HeatMeasure = 'remaining' | 'recorded' | 'movement'

/** What a heat map cell measures for one row, in its local currency. */
function measureOf(r: TbRow, measure: HeatMeasure): Cents {
  if (measure === 'movement') return r.after - r.recorded
  return (r.truth ?? 0) - (measure === 'remaining' ? r.after : r.recorded)
}

export interface HeatCell {
  company: string
  group: string
  /** Σ|value| in EUR cents over the cell's accounts. */
  eur: Cents
  accounts: number
}

export interface HeatMap {
  companies: string[]
  groups: string[]
  cells: Map<string, HeatCell>
  max: Cents
}

export const heatKey = (company: string, group: string) => `${company}/${group}`

export function heatMap(rows: readonly TbRow[], toEur: ToEur, measure: HeatMeasure): HeatMap {
  const cells = new Map<string, HeatCell>()
  const companies = new Set<string>()
  const groups = new Set<string>(ACCOUNT_GROUPS)
  for (const r of rows) {
    const group = accountGroup(r.account)
    companies.add(r.company)
    groups.add(group)
    const value = Math.abs(toEur(r.company, measureOf(r, measure)))
    if (!value) continue
    const k = heatKey(r.company, group)
    const cell = cells.get(k) ?? { company: r.company, group, eur: 0, accounts: 0 }
    cell.eur += value
    cell.accounts++
    cells.set(k, cell)
  }
  const max = Math.max(0, ...[...cells.values()].map((c) => c.eur))
  return { companies: [...companies].sort(), groups: [...groups].sort(), cells, max }
}

// ---------------------------------------------------------------- rows

/** Difference that remains after the run, in local currency (null without golden). */
export const remainingDiff = (r: TbRow): Cents | null => (r.truth === null ? null : r.after - r.truth)

/** Rows that matter: touched by an entry of the run, or off the truth before or after it. */
export function relevantRows(rows: readonly TbRow[]): TbRow[] {
  return rows.filter((r) => Object.values(r.delta).some((x) => x) || (r.truth !== null && (r.truth !== r.after || r.truth !== r.recorded)))
}
