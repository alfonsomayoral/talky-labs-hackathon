// @vitest-environment node
import type { Deliverables } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { devPhase, loadGolden } from '../test-utils/phase'
import { scoreTb } from '../score/tasks'
import { compareTrialBalance } from './trialBalance'

const fixture = await devPhase()

describe.skipIf(!fixture)('compareTrialBalance', () => {
  const golden = fixture ? loadGolden(fixture) : null!

  it('closes the whole gap with golden', () => {
    const tb = compareTrialBalance(golden.trialBalanceRecorded, golden.deliverables, golden.trialBalanceTruth)
    expect(tb.gapRecorded).toBeGreaterThan(0)
    expect(tb.gapAfter).toBe(0)
    expect(tb.score).toBe(1)
    for (const k of TASK_KEYS) expect(tb.movementByTask[k], k).toBeGreaterThan(0)
    for (const r of tb.rows) expect(r.after, `${r.company}/${r.account}`).toBe(r.truth)
  })

  it('matches score_tb on a partial delivery', () => {
    const partial = { ...golden.deliverables, ap: golden.deliverables.ap.slice(0, 100), close: [] } as Deliverables
    const tb = compareTrialBalance(golden.trialBalanceRecorded, partial, golden.trialBalanceTruth)
    const ref = scoreTb(golden.trialBalanceTruth, golden.trialBalanceRecorded, partial)
    expect(tb.score).toBe(ref.score)
    expect(tb.gapAfter! / 100).toBeCloseTo(ref.details.abs_difference_eur as number, 2)
  })

  it('works without truth', () => {
    const tb = compareTrialBalance(golden.trialBalanceRecorded, golden.deliverables, null)
    expect(tb).toMatchObject({ gapRecorded: null, gapAfter: null, score: null })
    expect(tb.rows.every((r) => r.truth === null)).toBe(true)
  })
})
