import { describe, expect, it } from 'vitest'
import type { BankAccount, BankLine, BankRecRow, JournalEntry, WorkItem } from '@/domain/types'
import { accountSummary, adjustmentsOf, balanceBridge, bookAmount, bookLinesOf, glAdjustments, itemByLine, matchShape, recView, unmatchedByCategory, type BookLine } from './model'

const bank = (id: string, amount: number, date = '2026-07-10'): BankLine => ({ bank_line: id, booking_date: date, value_date: date, amount, currency: 'EUR', text: id })
const book = (id: string, amount: number, date = '2026-07-10'): BookLine => ({ id, date, amount, text: id, partner: null, source: 'AP' })

// A month: a payroll in two lots against one book line (N:1), a SEPA batch against two payments (1:N),
// an unbooked fee with its adjustment and an outstanding payment without one.
const bankLines = [bank('B1', -500), bank('B2', -300, '2026-07-11'), bank('B3', -1000, '2026-07-05'), bank('FEE', -12, '2026-07-31')]
const monthBook = [book('J1#2', -800, '2026-07-11'), book('J2#2', -600, '2026-07-05'), book('J3#2', -400, '2026-07-05'), book('OUT#2', -250, '2026-07-30')]
const row: BankRecRow = {
  account: 'BIN-1200',
  company: '1200',
  matches: [
    { bank_lines: ['B1', 'B2'], book_lines: ['J1#2'] },
    { bank_lines: ['B3'], book_lines: ['J2#2', 'J3#2'] },
  ],
  unmatched_bank: [{ bank_line: 'FEE', category: 'BANK_FEE_NOT_BOOKED' }],
  unmatched_book: [{ book_line: 'OUT#2', category: 'OUTSTANDING_PAYMENT' }],
  adjustments: [
    {
      category: 'BANK_FEE_NOT_BOOKED',
      lines: [
        { company: '1200', account: '57200001', debit: 0, credit: 12 },
        { company: '1200', account: '62600000', debit: 12, credit: 0 },
      ],
    },
  ],
}

describe('bookAmount', () => {
  it('uses debit − credit for local accounts and the signed document amount for foreign ones', () => {
    expect(bookAmount({ debit: 0, credit: 500, currency: 'EUR', amount_doc: 500 }, 'EUR', 'EUR')).toBe(-500)
    expect(bookAmount({ debit: 0, credit: 44488, currency: 'USD', amount_doc: 2500 }, 'USD', 'MXN')).toBe(-2500)
    expect(bookAmount({ debit: 18564171, credit: 0, currency: 'MXN', amount_doc: 18564171 }, 'USD', 'MXN')).toBeNull()
  })

  it('keeps only the lines of the bank GL in its company', () => {
    const entries = [
      { id: 'E1', company: '1200', posting_date: '2026-07-01', header_text: 'h', source: 'AP', lines: [
        { line: 1, account: '40000000', debit: 100, credit: 0, currency: 'EUR', amount_doc: 100, text: '' },
        { line: 2, account: '57200001', debit: 0, credit: 100, currency: 'EUR', amount_doc: 100, text: '' },
      ] },
      { id: 'E2', company: '1100', posting_date: '2026-07-01', header_text: 'h', source: 'AP', lines: [{ line: 1, account: '57200001', debit: 5, credit: 0, currency: 'EUR', amount_doc: 5, text: '' }] },
    ] as unknown as JournalEntry[]
    const lines = bookLinesOf(entries, { company: '1200', gl_account: '57200001', currency: 'EUR' }, 'EUR')
    expect(lines.map((l) => [l.id, l.amount])).toEqual([['E1#2', -100]])
  })
})

describe('recView', () => {
  const view = recView(row, bankLines, monthBook, [])

  it('names the shape of each match', () => {
    expect(view.groups.map((g) => g.shape)).toEqual(['N:1', '1:N'])
    expect(matchShape(2, 2)).toBe('N:M')
    expect(view.groups.every((g) => g.diff === 0)).toBe(true)
  })

  it('orders blocks by date with matches first and keeps lone lines on their side', () => {
    expect(view.blocks.map((b) => (b.kind === 'match' ? `m${b.group.index}` : `${b.kind}:${b.line.id}`))).toEqual(['m1', 'm0', 'book:OUT#2', 'bank:FEE'])
  })

  it('reports lines the deliverable leaves out', () => {
    const partial = recView({ ...row, unmatched_bank: [] }, bankLines, monthBook, [])
    expect(partial.untreatedBank.map((l) => l.id)).toEqual(['FEE'])
    expect(partial.untreatedBook).toEqual([])
  })

  it('groups unmatched lines by category and says whether an adjustment exists', () => {
    const cats = unmatchedByCategory(row, view)
    expect(cats.map((c) => [c.category, c.adjusted, c.expectsAdjustment, c.amount])).toEqual([
      ['OUTSTANDING_PAYMENT', false, false, -250],
      ['BANK_FEE_NOT_BOOKED', true, true, -12],
    ])
  })
})

describe('balanceBridge', () => {
  const view = recView(row, bankLines, monthBook, [])
  const adjustments = adjustmentsOf(row, '57200001')
  // Book: opening 10 000 − 2 050 of the month. Bank: opening 10 000 − 1 812.
  const input = { statementOpening: 10_000, statementClosing: 8_188, statementMovement: -1_812, glClosing: 7_950, glMovement: -2_050, view, adjustments }
  const step = (id: string) => balanceBridge(input).find((s) => s.id === id)

  it('walks from the statement to the book with nothing unexplained', () => {
    expect(adjustments[0].glMovement).toBe(-12)
    expect(step('bank_only')?.amount).toBe(12)
    expect(step('book_only')?.amount).toBe(-250)
    expect(step('gap')).toBeUndefined()
    expect(step('book')?.amount).toBe(7_950)
  })

  it('leaves as residual only the items without adjustment', () => {
    expect(step('book_after')?.amount).toBe(7_938)
    expect(step('residual')?.amount).toBe(250)
  })

  it('leaves the adjustments out when they are in another currency', () => {
    expect(balanceBridge({ ...input, adjustments: null }).map((s) => s.id).at(-1)).toBe('book')
  })

  it('shows the inherited opening difference and any unexplained gap', () => {
    expect(balanceBridge({ ...input, glClosing: 7_850, glMovement: -2_050 }).find((s) => s.id === 'opening')?.amount).toBe(-100)
    // A GL line the app could not read (not in the month lines) shows up as unexplained.
    const missing = recView({ ...row, unmatched_book: [] }, bankLines, monthBook.slice(0, 3), [])
    expect(balanceBridge({ ...input, view: missing }).find((s) => s.id === 'gap')?.amount).toBe(-250)
  })
})

describe('glAdjustments', () => {
  it('takes every adjustment that moves this 572, also those filed under another account', () => {
    const other: BankRecRow = {
      account: 'BIN-1100',
      company: '1100',
      matches: [],
      unmatched_bank: [],
      unmatched_book: [],
      adjustments: [
        {
          category: 'WRONG_BANK_ACCOUNT',
          lines: [
            { company: '1100', account: '57200001', debit: 0, credit: 431 },
            { company: '1100', account: '57200002', debit: 431, credit: 0 },
          ],
        },
      ],
    }
    const own: BankRecRow = { ...other, account: 'CMA-1100', adjustments: [{ category: 'BANK_FEE_NOT_BOOKED', lines: [{ account: '57200002', debit: 0, credit: 30 }, { account: '62600000', debit: 30, credit: 0 }] }] }
    const adj = glAdjustments([other, own, row], '1100', '57200002')
    expect(adj.map((a) => [a.account, a.category, a.glMovement])).toEqual([
      ['BIN-1100', 'WRONG_BANK_ACCOUNT', 431],
      ['CMA-1100', 'BANK_FEE_NOT_BOOKED', -30],
    ])
  })
})

describe('account grid', () => {
  const account = { id: 'BIN-1200', company: '1200', gl_account: '57200001', currency: 'EUR' } as BankAccount
  const it_ = (key: string, status: WorkItem['status'], amount: number, evidence: WorkItem['evidence'] = []) =>
    ({ id: `bank_rec:${key}`, task: 'bank_rec', key, status, amount, evidence }) as WorkItem

  it('is open while some item has no adjustment, and missing without a row', () => {
    const items = [it_('BIN-1200/B1', 'AUTO', -800), it_('BIN-1200/OUT#2', 'OPEN', -250), it_('BIN-1100/X', 'OPEN', 1)]
    const s = accountSummary(account, row, { account: 'BIN-1200', month: '2026-07', format: 'n43', lines: bankLines, rawPath: null, opening: 10_000, closing: 8_188 }, items)
    expect([s.status, s.open, s.openAmount, s.matchedBankLines, s.statementLines]).toEqual(['open', 1, -250, 3, 4])
    expect(accountSummary(account, null, null, []).status).toBe('missing')
  })

  it('maps each line to the item that holds it', () => {
    const m = itemByLine([it_('BIN-1200/B1', 'AUTO', 0, [{ kind: 'bank', account: 'BIN-1200', bank_line: 'B1' }, { kind: 'journal', book_line: 'J1#2' }])], 'BIN-1200')
    expect(m.get('J1#2')).toBe('bank_rec:BIN-1200/B1')
  })
})
