// @vitest-environment node
// PLAN.md §0, «terminado»: every item of the 6 tasks opens with a balanced entry, its policy rule,
// evidence and its golden comparison. Checked on every July item, not on a sample.
import { devPhase, goldenRun, loadCore, loadGolden } from '../test-utils/phase'
import { entryImbalance } from '../ledger/entries'
import { deriveRun } from './deriveRun'
import { itemEntries } from './items'

const fixture = await devPhase()

describe.skipIf(!fixture)('every July item is explained (PLAN §0)', () => {
  const golden = fixture ? loadGolden(fixture) : null!
  const core = fixture ? loadCore(fixture, golden) : null!
  const run = fixture ? goldenRun(golden) : null!
  const data = fixture ? deriveRun(core, run, golden.trialBalanceRecorded ?? null) : null!

  it('has a policy rule, evidence and a golden comparison for each item', () => {
    const missing = data.items.flatMap((it) => [
      ...(it.policyRefs.length ? [] : [`${it.id}: sin regla`]),
      ...(it.evidence.length ? [] : [`${it.id}: sin evidencia`]),
      ...(data.score?.perItem[it.id] ? [] : [`${it.id}: sin comparación con golden`]),
    ])
    expect(missing).toEqual([])
  })

  it('balances every entry behind an item, per company', () => {
    const unbalanced = data.items.flatMap((it) =>
      itemEntries(core, run, it.id).flatMap((e) => ([...entryImbalance(e)].some(([, d]) => d !== 0) ? [it.id] : [])),
    )
    expect(unbalanced).toEqual([])
  })
})
