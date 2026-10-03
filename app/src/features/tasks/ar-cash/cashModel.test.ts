import { describe, expect, it } from 'vitest'
import type { ArCashRow, Company, JeLine, OpenItem, WorkItem } from '@/domain/types'
import { allocation, customerOpenItems, suspenseClearing } from './cashModel'

const receipt = (key: string, rowIndex: number, company: string, amount: number, date: string): WorkItem => ({
  id: `ar_cash:${key}`,
  task: 'ar_cash',
  key,
  company,
  title: key,
  counterparty: null,
  amount,
  currency: company === '3100' ? 'MXN' : 'EUR',
  date,
  status: 'AUTO',
  outcome: 'APPLIED',
  reasons: [],
  confidence: null,
  provenance: 'REFERENCE',
  policyRefs: [],
  evidence: [],
  tbImpact: 0,
  rowIndex,
})

const line = (account: string, debit: number, credit: number, partner: string | null = null, assignment: string | null = null): JeLine => ({
  company: '1100',
  account,
  debit,
  credit,
  partner,
  assignment,
})

const total = (xs: { amount: number }[]) => xs.reduce((s, x) => s + x.amount, 0)

describe('allocation', () => {
  it('treats a penalty as a source: the invoices are settled in full and the cash is short by the penalty (BL0000161)', () => {
    const row: ArCashRow = {
      bank_line: 'BL0000161',
      customer: 'C200001',
      applications: [
        { invoice: 'SU26-00035', amount: 46999466 },
        { invoice: 'SU26-00056', amount: 46815106 },
      ],
      residuals: [{ type: 'PENALTY', invoice: 'SU26-00056', amount: 212795 }],
      adjustment: [],
    }
    const a = allocation(row, 93601777)
    expect(a.unexplained).toBe(0)
    expect(a.sources.map((f) => f.label)).toEqual(['Abono en 55500000', 'Penalidad'])
    expect(a.uses.map((f) => f.ref)).toEqual(['SU26-00035', 'SU26-00056'])
    expect(total(a.sources)).toBe(total(a.uses))
  })

  it('treats a netting with the vendor twin as a source (BL0000567)', () => {
    const row: ArCashRow = {
      bank_line: 'BL0000567',
      customer: 'C200080',
      applications: [{ invoice: 'EN26-00014', amount: 43885431 }],
      residuals: [{ type: 'NETTING_AP', invoice: '26012023', amount: 828850 }],
      adjustment: [],
    }
    expect(allocation(row, 43056581).unexplained).toBe(0)
  })

  it('treats a duplicate payment as a use credited to 43800000', () => {
    const row: ArCashRow = { bank_line: 'BL0000808', customer: 'C200011', applications: [], residuals: [{ type: 'OVERPAYMENT_DUPLICATE', amount: 70291397 }], adjustment: [] }
    const a = allocation(row, 70291397)
    expect(a.uses).toHaveLength(1)
    expect(a.unexplained).toBe(0)
  })

  it('balances an unexplained remainder with a «queda en 55500000» use, and an excess with an uncovered source', () => {
    const short = allocation({ bank_line: 'B', customer: 'C', applications: [{ invoice: 'F1', amount: 60 }], residuals: [], adjustment: [] }, 100)
    expect(short.unexplained).toBe(40)
    expect(short.uses.at(-1)).toMatchObject({ key: 'left', amount: 40, tone: 'danger' })
    const over = allocation({ bank_line: 'B', customer: 'C', applications: [{ invoice: 'F1', amount: 130 }], residuals: [], adjustment: [] }, 100)
    expect(over.sources.at(-1)).toMatchObject({ key: 'uncovered', amount: 30 })
  })

  it('labels a promissory note and refers to its PAG assignment', () => {
    const a = allocation({ bank_line: 'B', customer: 'C', applications: [{ pagare: '3287513', amount: 15277656 }], residuals: [], adjustment: [] }, 15277656)
    expect(a.uses[0]).toMatchObject({ label: 'Pagaré 3287513', ref: 'PAG3287513', tone: 'info' })
  })
})

describe('suspenseClearing', () => {
  const companies = [
    { code: '1100', currency: 'EUR' },
    { code: '3100', currency: 'MXN' },
  ] as Company[]

  it('compares what the bank put in 55500000 with what the adjustments take out, per company', () => {
    const items = [receipt('A', 0, '1100', 1000, '2026-07-01'), receipt('B', 1, '1100', 500, '2026-07-02'), receipt('C', 2, '3100', 7000, '2026-07-03')]
    const rows: ArCashRow[] = [
      { bank_line: 'A', customer: 'C1', applications: [], residuals: [], adjustment: [line('55500000', 1000, 0), line('43000000', 0, 1000, 'C1', 'F1')] },
      { bank_line: 'B', customer: 'C1', applications: [], residuals: [], adjustment: [] },
      { bank_line: 'C', customer: 'C2', applications: [], residuals: [], adjustment: [{ ...line('55500000', 7000, 0), company: '3100' }] },
    ]
    expect(suspenseClearing(items, rows, { companies })).toEqual([
      { company: '1100', currency: 'EUR', receipts: 2, received: 1500, cleared: 1000, remaining: 500 },
      { company: '3100', currency: 'MXN', receipts: 1, received: 7000, cleared: 7000, remaining: 0 },
    ])
  })
})

describe('customerOpenItems', () => {
  const openItems: OpenItem[] = [
    { company: '1100', account: '43000000', partner: 'C200011', assignment: 'OB26-00046', balance: 70291397 },
    { company: '1100', account: '43000000', partner: 'C200011', assignment: 'OB26-00037', balance: 74140669 },
    { company: '1100', account: '43000000', partner: 'OTHER', assignment: 'OB26-00099', balance: 5 },
    { company: '1200', account: '43000000', partner: 'C200011', assignment: 'SU26-00001', balance: 7 },
    { company: '1100', account: '43000900', partner: 'C200011', assignment: 'OB26-00046', balance: 3699547 },
  ]
  const items = [receipt('BL0000654', 0, '1100', 70291397, '2026-07-27'), receipt('BL0000808', 1, '1100', 70291397, '2026-07-30')]
  const rows: ArCashRow[] = [
    {
      bank_line: 'BL0000654',
      customer: 'C200011',
      applications: [{ invoice: 'OB26-00046', amount: 70291397 }],
      residuals: [],
      adjustment: [line('55500000', 70291397, 0), line('43000000', 0, 70291397, 'C200011', 'OB26-00046')],
    },
    {
      bank_line: 'BL0000808',
      customer: 'C200011',
      applications: [],
      residuals: [{ type: 'OVERPAYMENT_DUPLICATE', amount: 70291397 }],
      adjustment: [line('55500000', 70291397, 0), line('43800000', 0, 70291397, 'C200011', null)],
    },
  ]
  const billing = [{ company: '1100', lines: [{ account: '43000000', debit: 1000, credit: 0, partner: 'C200011', assignment: 'OB26-00070' }] }]

  it('settles the invoice in the receipt that pays it, starting from open items plus the month invoices', () => {
    const lines = customerOpenItems(items[0], items, rows, billing, { openItems })
    expect(lines[0]).toEqual({ account: '43000000', assignment: 'OB26-00046', before: 70291397, after: 0, touched: true })
    expect(lines.map((l) => l.assignment)).toEqual(['OB26-00046', 'OB26-00037', 'OB26-00070'])
  })

  it('applies earlier receipts first, so the duplicate finds the invoice already settled and books a refund', () => {
    const lines = customerOpenItems(items[1], items, rows, billing, { openItems })
    expect(lines.find((l) => l.assignment === 'OB26-00046')).toBeUndefined()
    expect(lines[0]).toEqual({ account: '43800000', assignment: null, before: 0, after: -70291397, touched: true })
  })

  it('leaves out month invoices posted after the receipt', () => {
    const later = [{ ...billing[0], posting_date: '2026-07-31' }]
    const lines = customerOpenItems(items[0], items, rows, later, { openItems })
    expect(lines.map((l) => l.assignment)).not.toContain('OB26-00070')
  })

  it('returns nothing for a receipt without customer', () => {
    const noCustomer = [{ ...rows[0], customer: null }]
    expect(customerOpenItems(items[0], items, noCustomer, [], { openItems })).toEqual([])
  })
})
