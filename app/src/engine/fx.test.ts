import type { DatasetCore } from '@/domain/types'
import { makeToEur, rateAt } from './fx'

const core = {
  tasks: { close: { month: '2026-07', steps: [] } },
  companies: [
    { code: '1100', currency: 'EUR' },
    { code: '3100', currency: 'MXN' },
  ],
  fxRates: [
    { date: '2026-07-30', base: 'EUR', currency: 'MXN', rate: 20, source: 's' },
    { date: '2026-07-31', base: 'EUR', currency: 'MXN', rate: 19, source: 's' },
    { date: '2026-08-01', base: 'EUR', currency: 'MXN', rate: 25, source: 's' },
  ],
} as unknown as DatasetCore

describe('makeToEur', () => {
  it('uses the last rate published on or before the month end', () => {
    expect(rateAt(core, 'MXN', '2026-07-31')).toBe(19)
  })

  it('keeps EUR companies and converts MXN cents at the month-end rate', () => {
    const toEur = makeToEur(core)
    expect(toEur('1100', 1000)).toBe(1000)
    expect(toEur('3100', 1900)).toBe(100)
    expect(toEur(null, 500)).toBe(500)
  })
})
