// @vitest-environment node
import type { Deliverables } from '@/domain/types'
import { devPhase, goldenRun, loadGolden } from '../test-utils/phase'
import { diffItems } from './itemDiff'

const fixture = await devPhase()

describe.skipIf(!fixture)('diffItems', () => {
  const golden = fixture ? loadGolden(fixture) : null!
  const sub = (): Deliverables => structuredClone(goldenRun(golden).deliverables)
  const inexact = (d: Deliverables) =>
    Object.values(diffItems(golden.deliverables, d))
      .filter((s) => !s.exact)
      .map((s) => s.item)
      .sort()

  it('golden against itself is exact everywhere', () => {
    expect(inexact(sub())).toEqual([])
  })

  it('shows exactly the altered items', () => {
    const d = sub()
    const ap = d.ap.find((r) => r.decision === 'POST')!
    ap.decision = 'HOLD'
    const je = d.ap.find((r) => r.journal_entry && r !== ap)!
    je.journal_entry!.lines[0].debit += 50
    const cash = d.ar_cash[0]
    cash.applications = [...cash.applications, { invoice: 'X-1', amount: 1 }]
    const bank = d.bank_rec[0]
    const droppedMatch = bank.matches.pop()!
    const ic = d.ic.find((r) => r.adjustment.length)!
    ic.adjustment = []
    const close = d.close.find((r) => r.type === 'PREPAID')!
    close.amount += 10_000
    d.close.push({ type: 'ACCRUAL', company: '1100', vendor: 'V199999', amount: 100 })

    const ids = inexact(d)
    expect(ids).toEqual(
      [
        `ap:${ap.doc_id}`,
        `ap:${je.doc_id}`,
        `ar_cash:${cash.bank_line}`,
        `bank_rec:${bank.account}/${droppedMatch.bank_lines[0]}`,
        `ic:${[...ic.pair].sort().join('-')}/${ic.cause}`,
        `close:PREPAID/${close.company}/${close.invoice}`,
        'close:ACCRUAL/1100/V199999',
      ].sort(),
    )
    const perItem = diffItems(golden.deliverables, d)
    expect(perItem[`ap:${ap.doc_id}`].diffs[0]).toEqual({ path: 'decision', expected: 'POST', actual: 'HOLD' })
    expect(perItem[`ap:${je.doc_id}`].diffs.map((x) => x.path)).toEqual(['journal_entry.lines'])
    expect(perItem['close:ACCRUAL/1100/V199999'].diffs[0]).toMatchObject({ path: 'item', expected: null })
  })
})
