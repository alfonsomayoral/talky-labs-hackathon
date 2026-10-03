import { describe, expect, it } from 'vitest'
import type { IntercompanyAgreements, JournalEntry, JournalLine, WorkItem } from '@/domain/types'
import type { ToEur } from '@/engine'
import { icMatrix, interestCheck, pairBooks } from './model'

const ACCOUNTS = ['43300000', '40300000', '55200000', '40090000']
const currencyOf = (c: string) => (c === '3100' ? 'MXN' : 'EUR')
const toEur: ToEur = (company, cents) => (company === '3100' ? Math.round(cents / 18.9004) : cents)

const line = (account: string, debit: number, credit: number, partner: string | null, doc?: { currency: string; amount: number }): JournalLine => ({
  line: 1,
  account,
  debit,
  credit,
  currency: doc?.currency ?? 'EUR',
  amount_doc: doc?.amount ?? debit + credit,
  partner,
  cost_center: null,
  wbs: null,
  tax_code: null,
  assignment: null,
  text: '',
})

const entry = (id: string, company: string, reference: string, lines: JournalLine[], date = '2026-07-28'): JournalEntry => ({
  id,
  company,
  doc_type: 'IC',
  posting_date: date,
  document_date: date,
  reference,
  header_text: '',
  source: 'POOL',
  currency: currencyOf(company),
  lines,
})

const item = (key: string, amount: number, company = key.slice(0, 4)): WorkItem => ({ id: `ic:${key}`, key, amount, company, currency: 'EUR' }) as WorkItem

describe('icMatrix', () => {
  it('keeps every pair of the task, sums |difference| in EUR and lists the companies', () => {
    const m = icMatrix(
      [
        ['1000', '1100'],
        ['3100', '1000'],
      ],
      [item('1000-3100/INTEREST_DAY_COUNT', 83333), item('1000-1100/WRONG_TRADING_PARTNER', -14415889)],
      (it) => it.amount ?? 0,
    )
    expect(m.companies).toEqual(['1000', '1100', '3100'])
    expect(m.cells.get('1000-3100')?.eur).toBe(83333)
    expect(m.cells.get('1000-1100')?.items).toHaveLength(1)
    expect(m.cells.get('1000-1100')?.eur).toBe(14415889)
  })
})

describe('pairBooks', () => {
  const entries = [
    // CP2607281100: 1000 credits 1100, but 1100 books the sweep with partner 1200.
    entry('1000-1', '1000', 'CP2607281100', [line('57200001', 14415889, 0, null), line('55200000', 0, 14415889, '1100')]),
    entry('1100-1', '1100', 'CP2607281100', [line('57200001', 0, 14415889, null), line('55200000', 14415889, 0, '1200')]),
    // Pooling interest: one entry of 1000 with a line per participant.
    entry('1000-2', '1000', 'POOLINT2607', [line('55200000', 1000, 0, '1100'), line('55200000', 2000, 0, '1200')]),
    entry('1100-2', '1100', 'POOLINT2607', [line('55200000', 0, 1000, '1000')]),
    // 3100 books MXN with the EUR amount in amount_doc.
    entry('1000-3', '1000', 'KMI-INT-202607', [line('55200000', 2583333, 0, '3100'), line('76210000', 0, 2583333, null)], '2026-07-31'),
    entry('3100-1', '3100', 'KMI-INT-202607', [line('66210000', 47251000, 0, null, { currency: 'EUR', amount: 2500000 }), line('55200000', 0, 47251000, '1000', { currency: 'EUR', amount: 2500000 })], '2026-07-31'),
    // 3100's month-end valuation reversal: not an intercompany movement.
    { ...entry('3100-2', '3100', 'FXV-55200000-2606', [line('55200000', 1428585, 0, '1000')], '2026-07-01'), source: 'CLOSE_FX:reversal' },
    // AP invoice received from 1000 (partner V-IC1000).
    entry('1100-3', '1100', 'IC1000-26-0031', [line('62940000', 24544000, 0, null), line('40300000', 0, 29698240, 'V-IC1000')]),
  ]

  it('takes the lines whose partner is the other company, including V-IC partners', () => {
    const [a, b] = pairBooks(['1000', '1100'], entries, ACCOUNTS, currencyOf, toEur)
    expect(a.lines.map((l) => l.entry)).toEqual(['1000-1', '1000-2'])
    expect(b.lines.map((l) => [l.entry, l.partner])).toEqual([
      ['1100-1', '1200'],
      ['1100-2', '1000'],
      ['1100-3', 'V-IC1000'],
    ])
  })

  it('flags a mirror line with the wrong partner, but not another participant of a shared entry', () => {
    const [a, b] = pairBooks(['1000', '1100'], entries, ACCOUNTS, currencyOf, toEur)
    expect(b.lines.find((l) => l.entry === '1100-1')?.wrongPartner).toBe(true)
    expect(a.lines.some((l) => l.partner === '1200')).toBe(false)
    expect(b.totals).toEqual([
      { account: '40300000', eur: -29698240 },
      { account: '55200000', eur: -1000 },
    ])
  })

  it('values EUR lines of 3100 by their document amount, nets each account and skips FX valuations', () => {
    const [lender, borrower] = pairBooks(['1000', '3100'], entries, ACCOUNTS, currencyOf, toEur)
    expect(lender.totals).toEqual([{ account: '55200000', eur: 2583333 }])
    expect(borrower.lines[0]).toMatchObject({ local: -47251000, doc: { currency: 'EUR', amount: -2500000 }, eur: -2500000 })
    expect(borrower.totals).toEqual([{ account: '55200000', eur: -2500000 }])
  })
})

describe('interestCheck', () => {
  const loan: IntercompanyAgreements['loan'] = { id: 'KMI-2025-01', principal: 500000000, rate_bp: 600, basis: 'act/360', start: '2025-02-03', lender: '1000', borrower: '3100', note: '' }

  it('compares what each side booked with act/360 and 30/360', () => {
    const books = pairBooks(['1000', '3100'], [], ACCOUNTS, currencyOf, toEur)
    expect(interestCheck(loan, '2026-07', books)).toEqual({ days: 31, expected: 2583333, thirty: 2500000, lender: null, borrower: null })
  })

  it('reads the booked interest of the month from both books', () => {
    const books = pairBooks(
      ['1000', '3100'],
      [
        entry('1000-3', '1000', 'KMI-INT-202607', [line('55200000', 2583333, 0, '3100')]),
        entry('3100-1', '3100', 'KMI-INT-202607', [line('55200000', 0, 47251000, '1000', { currency: 'EUR', amount: 2500000 })]),
      ],
      ACCOUNTS,
      currencyOf,
      toEur,
    )
    const check = interestCheck(loan, '2026-07', books)
    expect(check.lender).toBe(2583333)
    expect(check.borrower).toBe(2500000)
  })
})
