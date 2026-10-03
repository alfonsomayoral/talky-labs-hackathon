import { jeMatch, normNum } from './primitives'
import { fsum, pyRound } from './py'

describe('Python semantics', () => {
  it('round() ties to even on the exact binary value', () => {
    expect(pyRound(0.03125, 4)).toBe(0.0312)
    expect(pyRound(0.09375, 4)).toBe(0.0938)
    expect(pyRound(2.675, 2)).toBe(2.67)
    expect(pyRound(12.125, 2)).toBe(12.12)
    expect(pyRound(-0.00005, 4)).toBe(-0.0001)
    expect(pyRound(0.99996, 4)).toBe(1)
  })

  it('sum() of floats is compensated like CPython ≥ 3.12', () => {
    expect(fsum(Array(10).fill(0.1))).toBe(1)
    expect(fsum([1e16, 1, -1e16])).toBe(1)
  })

  it('norm_num strips separators, case and leading zeros', () => {
    expect(normNum('00fv-2026/0012')).toBe('FV20260012')
    expect(normNum(null)).toBe('')
  })

  it('je_match pairs lines greedily within ±2 cents on the normalised key', () => {
    const gold = [
      { account: '40000000', debit: 0, credit: 1000, partner: 'V1' },
      { account: '62900000', debit: 1000, credit: 0, cost_center: 'CC-1' },
    ]
    expect(jeMatch(gold, gold)).toBe(1)
    expect(jeMatch(gold, [{ ...gold[0], credit: 1002 }, gold[1]])).toBe(1)
    expect(jeMatch(gold, [{ ...gold[0], credit: 1003 }, gold[1]])).toBe(0.5)
    // Partner only counts on open-item accounts; cost objects only on P&L.
    expect(jeMatch(gold, [gold[0], { ...gold[1], partner: 'X' }])).toBe(1)
    expect(jeMatch(gold, [{ ...gold[0], cost_center: 'CC-9' }, gold[1]])).toBe(1)
    expect(jeMatch(null, [])).toBe(1)
  })
})
