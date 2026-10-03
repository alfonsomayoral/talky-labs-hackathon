import { describe, expect, it } from 'vitest'
import type { ArBillingInvoice, ArBillingRow, BillingHistoryEntry, CloseRow, SalesContract, WorkItem } from '@/domain/types'
import { billingListRows, certificationCalc, invoiceFigures, invoiceNumber, wipFor } from './billingModel'

const item = (key: string, rowIndex: number, outcome = 'INVOICE'): WorkItem => ({
  id: `ar_billing:${key}`,
  task: 'ar_billing',
  key,
  company: '1100',
  title: key,
  counterparty: null,
  amount: null,
  currency: 'EUR',
  date: null,
  status: 'AUTO',
  outcome,
  reasons: [],
  confidence: null,
  provenance: 'REFERENCE',
  policyRefs: [],
  evidence: [],
  tbImpact: 0,
  rowIndex,
})

const cert = (contract: string, month: string, number: number, cumulative: number, approved: boolean): BillingHistoryEntry => ({
  id: `BILL-${contract}-${month.replace('-', '')}`,
  type: 'OBRA_CERTIFICATION',
  company: '1100',
  contract,
  customer: 'C1',
  month,
  cert: {
    id: `CERT-${number}`,
    contract,
    project: 'P',
    number,
    month,
    cumulative,
    previous: 0,
    current: 0,
    approved,
    approved_on: approved ? `${month}-27` : null,
    approver: 'Dirección Facultativa',
    lines: [],
  },
})

// BILL-CV-OB-3100-2501-202607 in the July golden (MXN, 5 al millar and advance amortisation).
const mexican: ArBillingInvoice = {
  date: '2026-07-31',
  due_date: '2026-08-20',
  tax_code: 'MR16',
  net: 2474947185,
  tax: 395991550,
  gross: 2870938735,
  retention: 0,
  deductions: [
    { code: 'MX5MILL', amount: 12374736, account: '63100000' },
    { code: 'ADV_AMORT', amount: 861281621, account: '43800000' },
  ],
  payable: 1997282378,
  face: null,
  lines: [
    { description: 'Capítulo 01', amount: 555241546, account: '70510000', wbs: 'OB-3100-2501.01' },
    { description: 'Capítulo 02', amount: 810792567, account: '70510000', wbs: 'OB-3100-2501.02' },
    { description: 'Capítulo 03', amount: 751962089, account: '70510000', wbs: 'OB-3100-2501.03' },
    { description: 'Capítulo 04', amount: 356950983, account: '70510000', wbs: 'OB-3100-2501.04' },
  ],
}

describe('invoiceFigures', () => {
  it('reproduces payable = gross − retention − deductions on the Mexican estimate', () => {
    const f = invoiceFigures(mexican)
    expect(f.expectedPayable).toBe(1997282378)
    expect(f.payableOk).toBe(true)
    expect(f.linesOk).toBe(true)
    expect(f.deductions.map((d) => d.code)).toEqual(['MX5MILL', 'ADV_AMORT'])
  })

  it('flags a payable or a line total that does not add up', () => {
    const f = invoiceFigures({ ...mexican, payable: mexican.payable + 500, lines: mexican.lines.slice(1) })
    expect(f.payableOk).toBe(false)
    expect(f.linesOk).toBe(false)
  })

  it('derives gross from net + tax when the row omits it', () => {
    const { gross: _, ...noGross } = mexican
    expect(invoiceFigures(noGross as ArBillingInvoice).gross).toBe(2870938735)
  })
})

describe('certificationCalc', () => {
  const contracts: SalesContract[] = [{ id: 'CV-2511', company: '1100', customer: 'C1', kind: 'OBRA', tax: 'R21', terms_days: 30, start: '2024-01-01', value: 1_000_000_000 }]

  it('takes the anterior from the last approved certification and lists the pending month it absorbs', () => {
    const history = [cert('CV-2511', '2026-04', 8, 500_000_000, true), cert('CV-2511', '2026-05', 9, 636_504_278, true), cert('CV-2511', '2026-06', 10, 750_175_906, false)]
    const c = certificationCalc('CV-2511', '2026-07', 223_107_590, history, contracts)
    expect(c.previous).toEqual({ number: 9, month: '2026-05', approvedOn: '2026-05-27' })
    expect(c.anterior).toBe(636_504_278)
    expect(c.aOrigen).toBe(636_504_278 + 223_107_590)
    expect(c.pendingMonths).toEqual(['2026-06'])
    expect(c.executed).toBeCloseTo(0.8596, 4)
  })

  it('ignores certifications of this month or later and of other contracts', () => {
    const history = [cert('CV-2511', '2026-07', 11, 9, true), cert('CV-OTHER', '2026-06', 3, 7, true)]
    const c = certificationCalc('CV-2511', '2026-07', 100, history, contracts)
    expect(c.previous).toBeNull()
    expect(c.anterior).toBe(0)
    expect(c.aOrigen).toBe(100)
  })

  it('keeps a origen open when the pending work is unknown', () => {
    const c = certificationCalc('CV-2511', '2026-07', null, [cert('CV-2511', '2026-06', 10, 5, true)], [])
    expect(c.aOrigen).toBeNull()
    expect(c.executed).toBeNull()
  })
})

describe('wipFor', () => {
  it('links a pending certification to its WIP_REVENUE close item', () => {
    const close: CloseRow[] = [
      { type: 'ACCRUAL', company: '1100', vendor: 'V1', amount: 5 },
      { type: 'WIP_REVENUE', company: '2100', billing_item: 'BILL-CV-OB-2100-2503-202607', amount: 28990273 },
    ]
    expect(wipFor('BILL-CV-OB-2100-2503-202607', close)).toEqual({
      id: 'close:WIP_REVENUE/2100/BILL-CV-OB-2100-2503-202607',
      company: '2100',
      amount: 28990273,
    })
    expect(wipFor('BILL-X', close)).toBeNull()
  })
})

describe('invoiceNumber and billingListRows', () => {
  const je = (reference: string | null, assignment: string | null) => ({
    company: '1100',
    reference,
    lines: [{ account: '43000000', debit: 10, credit: 0, assignment }],
  })

  it('reads the number from the entry reference, else from the receivable assignment', () => {
    expect(invoiceNumber({ billing_item: 'B', expected: 'INVOICE', journal_entry: je('OB26-00057', null) })).toBe('OB26-00057')
    expect(invoiceNumber({ billing_item: 'B', expected: 'INVOICE', journal_entry: je(null, 'SU26-00107') })).toBe('SU26-00107')
    expect(invoiceNumber({ billing_item: 'B', expected: 'SKIP_PENDING_APPROVAL', journal_entry: null })).toBeNull()
  })

  it('fills type, contract and customer from the inbox item.json when the row lacks them', () => {
    const rows: ArBillingRow[] = [{ billing_item: 'B1', expected: 'SKIP_PENDING_APPROVAL' }]
    const list = billingListRows([item('B1', 0, 'SKIP_PENDING_APPROVAL')], rows, [
      { item: 'B1', files: [], meta: { billing_item: 'B1', type: 'OBRA_CERTIFICATION', company: '2100', contract: 'CV-1', customer: 'C9', month: '2026-07', documents: [] } },
    ])
    expect(list[0]).toMatchObject({ type: 'OBRA_CERTIFICATION', contract: 'CV-1', customer: 'C9', month: '2026-07', invoiceNumber: null })
  })
})
