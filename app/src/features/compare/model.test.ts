// @vitest-environment node
import type { DatasetCore, Deliverables, Golden, ItemScore, RunBundle } from '@/domain/types'
import { deriveRun } from '@/engine'
import { devPhase, goldenRun, loadCore, loadGolden } from '@/engine/test-utils/phase'
import { fixtureCore, fixtureDeliverables, fixtureRun } from '@/features/item/kit/testing/fixture'
import { applyCompareParams, diffRows, parseCompareParams, taskSummaries } from './model'

const item = (id: string, score: number | null, diffs: ItemScore['diffs'] = []): ItemScore => ({ item: id, score, exact: diffs.length === 0, diffs })

const goldenOf = (deliverables: Deliverables): Golden => ({ deliverables, trialBalanceTruth: [], trialBalanceRecorded: [], summary: null })

/** Score of `sub` against the fixture as golden, through the same engine the page reads. */
function scoreFixture(sub: Deliverables) {
  const core = { ...fixtureCore(), golden: goldenOf(fixtureDeliverables()) } as DatasetCore
  return deriveRun(core, fixtureRun({ deliverables: sub }), null).score!
}

describe('diffRows', () => {
  const perItem: Record<string, ItemScore> = {
    'ap:A1': item('ap:A1', 1),
    'ap:A2': item('ap:A2', 0.7, [{ path: 'decision', expected: 'REJECT', actual: 'POST' }]),
    'ap:A3': item('ap:A3', 0, [{ path: 'item', expected: 'A3', actual: null }]),
    'ap:A9': item('ap:A9', null, [{ path: 'item', expected: null, actual: 'A9' }]),
    'close:ACCRUAL/1000/V1': item('close:ACCRUAL/1000/V1', 0.5, [{ path: 'amount', expected: 30000, actual: 31000 }]),
  }

  it('lists only the items that differ unless all are asked for', () => {
    expect(diffRows(perItem).map((r) => r.id)).not.toContain('ap:A1')
    expect(diffRows(perItem, { all: true }).map((r) => r.id)).toContain('ap:A1')
  })

  it('classifies missing, extra and different items', () => {
    const kinds = Object.fromEntries(diffRows(perItem, { all: true }).map((r) => [r.id, r.kind]))
    expect(kinds).toEqual({ 'ap:A1': 'exact', 'ap:A2': 'different', 'ap:A3': 'missing', 'ap:A9': 'extra', 'close:ACCRUAL/1000/V1': 'different' })
    expect(diffRows({ 'bank_rec:B1': item('bank_rec:B1', 0.9) }, { all: true })[0].kind).toBe('inherited')
  })

  it('orders by points lost: task weight × (1 − item score) ÷ golden items of the task, unknown last', () => {
    const rows = diffRows(perItem)
    // AP: 0.3 × 1 ÷ 3 golden items = 10 points; 0.3 × 0.3 ÷ 3 = 3. Close: 0.1 × 0.5 ÷ 1 = 5.
    expect(rows.map((r) => [r.id, r.loss === null ? null : Number(r.loss.toFixed(6))])).toEqual([
      ['ap:A3', 10],
      ['close:ACCRUAL/1000/V1', 5],
      ['ap:A2', 3],
      ['ap:A9', null],
    ])
  })

  it('filters by task', () => {
    expect(diffRows(perItem, { task: 'close' }).map((r) => r.id)).toEqual(['close:ACCRUAL/1000/V1'])
  })
})

describe('taskSummaries', () => {
  it('follows the pipeline, ends with the trial balance and adds weight × score up to the total', () => {
    const score = scoreFixture(fixtureDeliverables())
    const rows = taskSummaries(score)
    expect(rows.map((r) => r.task)).toEqual(['ap', 'ar_billing', 'bank_rec', 'ar_cash', 'ic', 'close', 'trial_balance'])
    const sum = rows.reduce((s, r) => s + r.contributes, 0)
    expect(sum).toBeCloseTo(score.total, 1)
    expect(rows.find((r) => r.task === 'ap')!.differing).toBe(0)
  })
})

describe('compare params', () => {
  it('reads and writes ?vista= and ?tarea=, keeping the others', () => {
    expect(parseCompareParams(new URLSearchParams(''))).toEqual({ view: 'diff', task: null })
    expect(parseCompareParams(new URLSearchParams('vista=todo&tarea=ic'))).toEqual({ view: 'all', task: 'ic' })
    expect(parseCompareParams(new URLSearchParams('tarea=nope')).task).toBeNull()
    const next = applyCompareParams(new URLSearchParams('item=ap:A1&vista=todo'), { view: 'diff', task: 'ap' })
    expect(next.toString()).toBe('item=ap%3AA1&tarea=ap')
  })
})

// Gate 4: over an altered delivery, Comparar lists exactly the altered items.
describe('gate: an altered delivery shows exactly the altered items', () => {
  it('on the fixture', () => {
    const sub = fixtureDeliverables()
    sub.ap.find((r) => r.doc_id === 'A2')!.decision = 'POST'
    sub.ar_billing.find((r) => r.billing_item === 'B3')!.invoice!.net += 100
    sub.close.find((r) => r.type === 'ACCRUAL')!.amount += 5000

    const ids = diffRows(scoreFixture(sub).perItem).map((r) => r.id).sort()
    expect(ids).toEqual(['ap:A2', 'ar_billing:B3', 'close:ACCRUAL/1000/V1'])
  })

  it('golden against itself lists nothing', () => {
    expect(diffRows(scoreFixture(fixtureDeliverables()).perItem)).toEqual([])
  })
})

const phase = await devPhase()

describe.skipIf(!phase)('gate on July (phase_dev)', () => {
  it('lists exactly the altered rows of a delivery built from golden', () => {
    const golden = loadGolden(phase!)
    const core = loadCore(phase!, golden)
    const run: RunBundle = goldenRun(golden)
    const d = run.deliverables
    const ap = d.ap.find((r) => r.decision === 'POST')!
    ap.decision = 'HOLD'
    const cash = d.ar_cash[0]
    cash.customer = 'C-NOPE'
    const close = d.close.find((r) => r.type === 'PREPAID')!
    close.amount += 10_000

    const ids = diffRows(deriveRun(core, run, null).score!.perItem).map((r) => r.id).sort()
    expect(ids).toEqual([`ap:${ap.doc_id}`, `ar_cash:${cash.bank_line}`, `close:PREPAID/${close.company}/${close.invoice}`].sort())
  })
})
