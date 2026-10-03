import { describe, expect, it } from 'vitest'
import type { ApInvoice, ArInvoice, CloseRow, OpenItem } from '@/domain/types'
import { agingOf, closeRowsOf, fxBreakdown, fxTarget, prepaidFraction, vendorHistory } from './model'

describe('closeRowsOf', () => {
  const rows = [
    { type: 'ACCRUAL', company: '1100', vendor: 'V100028', amount: 100 },
    { type: 'ACCRUAL', company: '1100', vendor: 'V100028', amount: 200 },
    { type: 'ACCRUAL', company: '1200', vendor: 'V100028', amount: 300 },
    { type: 'FX_REVAL', company: '3100', item: 'GL:16330000', amount: -599350000 },
  ] as CloseRow[]

  it('groups the accrual rows of a vendor and company, and finds keys with a colon', () => {
    expect(closeRowsOf(rows, { key: 'ACCRUAL/1100/V100028' }).map((r) => r.amount)).toEqual([100, 200])
    expect(closeRowsOf(rows, { key: 'FX_REVAL/3100/GL:16330000' })).toHaveLength(1)
  })
})

describe('vendorHistory', () => {
  const inv = (issue_date: string, net: number, extra: Partial<ApInvoice> = {}) => ({ vendor: 'V100028', company: '1100', kind: 'invoice', issue_date, net, ...extra }) as ApInvoice

  it('sums the net per month over the 12 months before the close and averages the months with invoices', () => {
    const h = vendorHistory(
      [inv('2026-07-20', 1000), inv('2026-07-21', 500), inv('2026-05-18', 3000), inv('2025-07-31', 9999), inv('2026-06-18', 400, { kind: 'credit_note' }), inv('2026-06-01', 7, { company: '1200' })],
      'V100028',
      '1100',
      '2026-07',
    )
    expect(h.months[0]).toBe('2025-08')
    expect(h.months.at(-1)).toBe('2026-07')
    expect(h.values.at(-1)).toBe(1500)
    expect(h.values.at(-3)).toBe(3000)
    expect(h.values.at(-2)).toBe(0)
    expect(h.average).toBe(2250)
  })

  it('has no average without invoices', () => {
    expect(vendorHistory([], 'V1', '1000', '2026-07').average).toBeNull()
  })
})

describe('prepaidFraction', () => {
  it('reads (k/n) from the entry header', () => {
    expect(prepaidFraction('Periodificación gasto anticipado FV-2026-03360 (7/12)')).toEqual({ k: 7, n: 12 })
    expect(prepaidFraction('Sin fracción')).toBeNull()
    expect(prepaidFraction('(13/12)')).toBeNull()
  })
})

describe('fxBreakdown', () => {
  it('derives the value at the closing rate and the book value from the row', () => {
    // 3100's EUR loan: 5.000.000 EUR at 18,9004 MXN/EUR, revalued by −5.993.500 MXN.
    expect(fxBreakdown({ type: 'FX_REVAL', item: 'GL:16330000', currency: 'EUR', foreign: 500000000, rate: 18.9004, amount: -599350000 })).toEqual({
      currency: 'EUR',
      foreign: 500000000,
      rate: 18.9004,
      value: 9450200000,
      book: 10049550000,
    })
  })

  it('is null when the row does not carry the foreign amount and the rate', () => {
    expect(fxBreakdown({ type: 'FX_REVAL', item: 'AP:API004482', amount: -1567 })).toBeNull()
  })

  it('tells what the item points to', () => {
    expect(fxTarget('AP:API004559')).toEqual({ kind: 'ap', id: 'API004559' })
    expect(fxTarget('BANK:BANH-3100-USD')).toEqual({ kind: 'bank', id: 'BANH-3100-USD' })
  })
})

describe('agingOf', () => {
  // C200076 in July: two invoices over 365 days, one over 180, two current.
  const invoices = [
    ['SU25-00086', '2025-06-30'],
    ['SU25-00103', '2025-07-30'],
    ['SU25-00193', '2025-12-30'],
    ['SU26-00087', '2026-06-30'],
    ['SU26-00123', '2026-08-30'],
  ].map(([id, due_date]) => ({ id, due_date, customer: 'C200076' }) as ArInvoice)
  const open = (assignment: string, balance: number, account = '43000000'): OpenItem => ({ company: '1200', account, partner: 'C200076', assignment, balance })
  const items = [open('SU25-00086', 526350), open('SU25-00103', 526350), open('SU25-00193', 421081), open('SU26-00087', 1052700), open('SU26-00123', 1052700), open('G-1', 5000, '43000900')]

  it('provisions 100 % over 365 days and floor(50 %) over 180, with strict thresholds', () => {
    const a = agingOf(items, invoices, 'C200076', '1200', '2026-07-31', false)
    expect(a.lines.map((l) => [l.invoice, l.days, l.bucket])).toEqual([
      ['SU25-00086', 396, 'over365'],
      ['SU25-00103', 366, 'over365'],
      ['SU25-00193', 213, 'over180'],
      ['SU26-00087', 31, 'current'],
      ['SU26-00123', -30, 'current'],
    ])
    expect(a.required).toBe(526350 + 526350 + 210540)
    expect(a.totals.over180).toBe(421081)
  })

  it('provisions everything, guarantees included, when the customer is insolvent', () => {
    const a = agingOf(items, invoices, 'C200076', '1200', '2026-07-31', true)
    expect(a.required).toBe(526350 + 526350 + 421081 + 1052700 + 1052700 + 5000)
  })
})
