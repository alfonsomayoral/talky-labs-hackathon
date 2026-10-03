import { describe, expect, it } from 'vitest'
import type { TbRow, TrialBalanceComparison } from '@/domain/types'
import type { ToEur } from '@/engine'
import { gapWaterfall, heatKey, heatMap, relevantRows } from './model'

// 3100 books MXN at 20 MXN per EUR; the rest is EUR.
const toEur: ToEur = (company, cents) => (company === '3100' ? Math.round(cents / 20) : cents)

const row = (company: string, account: string, recorded: number, delta: TbRow['delta'], truth: number | null): TbRow => ({
  company,
  account,
  recorded,
  delta,
  after: recorded + Object.values(delta).reduce((s, x) => s + (x ?? 0), 0),
  truth,
})

// AR cash only squares 43000000 once AR billing has posted it: the gap is not additive.
const rows = [
  row('1100', '43000000', 0, { ar_billing: 1000, ar_cash: -1000 }, 0),
  row('1100', '70500000', 0, { ar_billing: -1000 }, -1000),
  row('1100', '57200000', 0, { ar_cash: 1000 }, 1000),
  row('3100', '40000000', 0, { ap: -20_000 }, -40_000),
  row('3100', '62000000', 500, {}, 500),
]

const tb = (truth: boolean): TrialBalanceComparison => ({
  rows: truth ? rows : rows.map((r) => ({ ...r, truth: null })),
  gapRecorded: truth ? 1 : null,
  gapAfter: truth ? 1 : null,
  score: null,
  movementByTask: { ap: 0, ar_billing: 0, ar_cash: 0, bank_rec: 0, ic: 0, close: 0 },
})

describe('gapWaterfall', () => {
  it('adds the tasks in pipeline order and its steps add up to recorded − after, in EUR', () => {
    const w = gapWaterfall(tb(true), toEur)!
    // 1000 (70500000) + 1000 (57200000) + 40000 MXN = 2000 EUR in 3100.
    expect(w.recorded).toBe(4000)
    const byTask = Object.fromEntries(w.steps.map((s) => [s.task, s.closed]))
    expect(byTask).toEqual({ ap: 1000, ar_billing: 0, bank_rec: 0, ar_cash: 2000, ic: 0, close: 0 })
    expect(w.after).toBe(1000)
    expect(w.steps.reduce((s, x) => s + x.closed, 0)).toBe(w.recorded - w.after)
    expect(w.steps.at(-1)!.remaining).toBe(w.after)
  })

  it('the order decides which task gets the credit', () => {
    const w = gapWaterfall(tb(true), toEur, ['ar_cash', 'ar_billing'])!
    expect(w.steps.map((s) => s.closed)).toEqual([0, 2000])
  })

  it('is null without golden', () => {
    expect(gapWaterfall(tb(false), toEur)).toBeNull()
  })
})

describe('heatMap', () => {
  it('sums |gap| in EUR per company and account group', () => {
    const m = heatMap(rows, toEur, 'remaining')
    expect(m.companies).toEqual(['1100', '3100'])
    expect(m.groups).toEqual(['1', '2', '3', '4', '5', '6', '7'])
    expect(m.cells.get(heatKey('3100', '4'))).toEqual({ company: '3100', group: '4', eur: 1000, accounts: 1 })
    expect(m.cells.has(heatKey('1100', '4'))).toBe(false)
    expect(m.max).toBe(1000)
  })

  it('measures the gap before the run or the movement of the run', () => {
    expect(heatMap(rows, toEur, 'recorded').cells.get(heatKey('1100', '7'))?.eur).toBe(1000)
    expect(heatMap(rows, toEur, 'movement').cells.get(heatKey('1100', '4'))).toBeUndefined()
    expect(heatMap(rows, toEur, 'movement').cells.get(heatKey('3100', '4'))?.eur).toBe(1000)
  })
})

describe('relevantRows', () => {
  it('drops rows that no entry touches and that already match the truth', () => {
    expect(relevantRows(rows).map((r) => r.account)).toEqual(['43000000', '70500000', '57200000', '40000000'])
  })
})
