// @vitest-environment node
import type { RunBundle } from '@/domain/types'
import { devPhase, goldenRun, loadCore, loadGolden } from '../test-utils/phase'
import { validateDeliverables } from './validate'

const fixture = await devPhase()

describe.skipIf(!fixture)('validateDeliverables', () => {
  const golden = fixture ? loadGolden(fixture) : null!
  const core = fixture ? loadCore(fixture, golden) : null!
  const fresh = (): RunBundle => structuredClone(goldenRun(golden))

  it('accepts golden as delivered', () => {
    const report = validateDeliverables(core, fresh())
    expect(report.ok).toBe(true)
    for (const f of Object.values(report.files)) {
      expect(f.errors, f.task).toEqual([])
      expect(f.missingKeys, f.task).toEqual([])
    }
    expect(report.files.ap).toMatchObject({ rows: 305, expected: 305 })
    expect(report.files.bank_rec).toMatchObject({ rows: 12, expected: 12 })
    expect(report.files.ic.expected).toBeNull()
  })

  it('catches an unbalanced entry', () => {
    const run = fresh()
    const row = run.deliverables.ap.find((r) => r.journal_entry)!
    row.journal_entry!.lines[0].debit += 1
    const bank = run.deliverables.bank_rec[0]
    bank.adjustments[1].lines[0].credit += 5
    const report = validateDeliverables(core, run)
    expect(report.ok).toBe(false)
    expect(report.files.ap.unbalancedEntries).toEqual([row.doc_id])
    expect(report.files.bank_rec.unbalancedEntries).toEqual([`${bank.account}/adjustments[1]`])
  })

  it('flags a missing file', () => {
    const run = fresh()
    run.present.ic = false
    run.deliverables.ic = []
    const report = validateDeliverables(core, run)
    expect(report.ok).toBe(false)
    expect(report.files.ic).toMatchObject({ present: false, rows: 0, errors: ['Falta el fichero ic.jsonl'] })
  })

  it('reports keys, enums, cents and accounts', () => {
    const run = fresh()
    const [first, second] = run.deliverables.ap
    run.deliverables.ap = [first, { ...first }, { ...second, doc_id: 'API999999', decision: 'MAYBE' as never, net: 10.5 }]
    run.deliverables.ap[0].lines = [{ ...run.deliverables.ap[0].lines[0], account: '99999999' }]
    run.deliverables.bank_rec[0].unmatched_bank[0].category = 'NOT_A_CATEGORY'
    const report = validateDeliverables(core, run)
    const ap = report.files.ap
    expect(ap.duplicateKeys).toEqual([first.doc_id])
    expect(ap.extraKeys).toEqual(['API999999'])
    expect(ap.missingKeys).toHaveLength(304)
    expect(ap.invalidValues).toContainEqual({ key: 'API999999', field: 'decision', value: 'MAYBE' })
    expect(ap.nonIntegerAmounts).toBe(1)
    expect(ap.unknownAccounts).toEqual(['99999999'])
    expect(report.files.bank_rec.invalidValues[0]).toMatchObject({ field: 'unmatched_bank.category', value: 'NOT_A_CATEGORY' })
  })
})
