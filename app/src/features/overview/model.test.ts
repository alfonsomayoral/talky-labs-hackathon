import type { AttentionItem, BankRecRow, Company, FileValidation, FxRate, TaskKey, TbRow, ValidationReport, WorkItem } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { formatPercent } from '@/lib/format'
import {
  attentionSummary,
  balanceSummary,
  banksControl,
  deliveryControl,
  eurConverter,
  intercompanyControl,
  longMonth,
  mosaicRows,
  outcomeBreakdown,
  pending555,
  scoreFacts,
} from './model'

const company = (code: string, currency = 'EUR') => ({ code, currency }) as Company
const COMPANIES = [company('1000'), company('1100'), company('3100', 'MXN')]
const rate = (date: string, value: number, currency = 'MXN'): FxRate => ({ date, base: 'EUR', currency, rate: value, source: 'SYN-BCE' })
const FX = [rate('2026-07-30', 18.8), rate('2026-07-31', 20), rate('2026-08-01', 25), rate('2026-07-31', 1.1, 'USD')]
const toEur = eurConverter(COMPANIES, FX, '2026-07')

const tb = (company: string, account: string, recorded: number, after: number, truth: number | null = null, delta: TbRow['delta'] = {}): TbRow => ({
  company,
  account,
  recorded,
  after,
  truth,
  delta,
})

let seq = 0
const item = (task: TaskKey, outcome: string, status: WorkItem['status'], extra: Partial<WorkItem> = {}): WorkItem => ({
  id: `${task}:${++seq}`,
  task,
  key: String(seq),
  company: '1000',
  title: `${task} ${seq}`,
  counterparty: null,
  amount: null,
  currency: 'EUR',
  date: null,
  status,
  outcome,
  reasons: [],
  confidence: null,
  provenance: 'REFERENCE',
  policyRefs: [],
  evidence: [],
  tbImpact: 0,
  rowIndex: 0,
  ...extra,
})

describe('longMonth', () => {
  it('spells the month being closed', () => {
    expect(longMonth('2026-07')).toBe('julio de 2026')
  })
})

describe('eurConverter', () => {
  it('uses the last rate of the month and keeps EUR companies as they are', () => {
    expect(toEur('1000', 12_345)).toBe(12_345)
    expect(toEur('3100', 2_000)).toBe(100)
    expect(toEur(null, 500)).toBe(500)
  })

  it('gives NaN when a currency has no rate, so totals show «—» instead of a wrong figure', () => {
    expect(eurConverter([company('9000', 'GBP')], FX, '2026-07')('9000', 100)).toBeNaN()
  })
})

describe('outcomeBreakdown', () => {
  it('counts one task by outcome with catalog labels, most frequent first', () => {
    const items = [
      item('ap', 'POST', 'AUTO'),
      item('ap', 'HOLD', 'BLOCKED'),
      item('ap', 'POST', 'AUTO'),
      item('ap', 'SOMETHING_NEW', 'OPEN'),
      item('bank_rec', 'MATCH', 'AUTO'),
    ]
    expect(outcomeBreakdown(items, 'ap')).toEqual([
      { outcome: 'POST', label: 'Contabilizar', count: 2 },
      { outcome: 'HOLD', label: 'Retener', count: 1 },
      { outcome: 'SOMETHING_NEW', label: 'SOMETHING_NEW', count: 1 },
    ])
    expect(outcomeBreakdown(items, 'bank_rec')).toEqual([{ outcome: 'MATCH', label: 'Casado', count: 1 }])
  })
})

describe('scoreFacts', () => {
  it('lists the AP sub-scores present in details', () => {
    expect(scoreFacts('ap', { decision_macro_f1: 1, header: 0.5, per_decision_f1: {} })).toEqual([
      { label: 'Decisión (F1)', value: formatPercent(1) },
      { label: 'Cabecera', value: formatPercent(0.5) },
    ])
  })

  it('summarises the other tasks from their counters', () => {
    expect(scoreFacts('bank_rec', { per_account: { A: 1, B: 0.92, C: 1 } })).toEqual([{ label: 'Cuentas al 100 %', value: '2 de 3' }])
    expect(scoreFacts('ic', { differences: 5, detected: 4 })).toEqual([{ label: 'Diferencias detectadas', value: '4 de 5' }])
  })
})

describe('attentionSummary', () => {
  it('counts by task and adds the impact in EUR', () => {
    const fx = item('close', 'FX_REVAL', 'NEEDS_HUMAN', { company: '3100' })
    const byId = new Map([[fx.id, fx]])
    const att = (id: string, impact: number) => ({ item: id, impact, priority: 'P1' }) as AttentionItem
    const s = attentionSummary([att(fx.id, 2_000), att('ap:API1', 300)], byId, toEur)
    expect(s.count).toBe(2)
    expect(s.impactEur).toBe(100 + 300)
    expect(s.byTask.close).toBe(1)
    expect(s.byTask.ap).toBe(1)
  })
})

describe('balanceSummary', () => {
  it('measures the gaps and the movement per task in EUR', () => {
    const rows = [tb('1000', '43000000', 100, 300, 300, { ap: 200 }), tb('3100', '40000000', 0, -2_000, -4_000, { ap: -2_000 })]
    const s = balanceSummary({ rows, gapRecorded: 4_200, gapAfter: 2_000, score: 0.5, movementByTask: {} as never }, toEur)
    expect(s.gapRecordedEur).toBe(200 + 200)
    expect(s.gapAfterEur).toBe(0 + 100)
    expect(s.movement[0]).toEqual({ task: 'ap', amountEur: 200 + 100 })
  })

  it('has no gaps without golden', () => {
    const s = balanceSummary({ rows: [tb('1000', '43000000', 100, 300)], gapRecorded: null, gapAfter: null, score: null, movementByTask: {} as never }, toEur)
    expect(s.gapRecordedEur).toBeNull()
    expect(s.score).toBeNull()
  })
})

describe('pending555', () => {
  it('is green only when every company ends at zero', () => {
    const cleared = pending555([tb('1100', '55500000', -5_000, 0), tb('3100', '55500000', -40_000, 0), tb('1100', '43000000', 1, 1)], toEur)
    expect(cleared).toEqual({ tone: 'ok', recordedEur: -5_000 - 2_000, afterEur: 0, remaining: [] })

    const left = pending555([tb('1100', '55500000', -5_000, 0), tb('3100', '55500000', -40_000, -2_000)], toEur)
    expect(left.tone).toBe('warn')
    expect(left.remaining).toEqual([{ company: '3100', after: -2_000 }])
    expect(left.afterEur).toBe(-100)
  })
})

describe('banksControl', () => {
  const row = (account: string, company: string, adjustments: string[] = []) =>
    ({ account, company, matches: [], unmatched_bank: [], unmatched_book: [], adjustments: adjustments.map((category) => ({ category, lines: [] })) }) as BankRecRow
  const bank = (account: string, outcome: string, status: WorkItem['status'] = 'OPEN', company = '1100') =>
    item('bank_rec', outcome, status, { key: `${account}/L${seq}`, company })

  it('treats differences that need no adjustment as reconciling items', () => {
    const c = banksControl(['A', 'B'], [row('A', '1100'), row('B', '1100')], [bank('A', 'OUTSTANDING_PAYMENT'), bank('B', 'MATCH', 'AUTO')])
    expect(c).toMatchObject({ tone: 'ok', total: 2, reconciled: 2, reconcilingItems: 1, unexplained: [], missing: [] })
  })

  it('accepts an adjustment booked on the other account of the same company', () => {
    const c = banksControl(['A', 'B'], [row('A', '1100', ['WRONG_BANK_ACCOUNT']), row('B', '1100')], [bank('B', 'WRONG_BANK_ACCOUNT')])
    expect(c).toMatchObject({ tone: 'ok', reconciled: 2 })
  })

  it('flags an open difference that needs a missing adjustment, and accounts not delivered', () => {
    const c = banksControl(['A', 'B', 'C'], [row('A', '1100'), row('B', '1200', ['BANK_FEE_NOT_BOOKED'])], [bank('A', 'BANK_FEE_NOT_BOOKED'), bank('B', 'UNKNOWN_CATEGORY', 'OPEN', '1200')])
    expect(c).toMatchObject({ tone: 'danger', total: 3, reconciled: 0, missing: ['C'], unexplained: ['A', 'B'] })
  })
})

describe('intercompanyControl', () => {
  it('nets each pair in EUR and compares it with the correct net when golden exists', () => {
    const rows = [
      tb('1000', '24230000', 500, 500, 500),
      tb('3100', '16330000', -12_000, -10_000, -10_000),
      tb('1000', '43300000', 900, 900, 900),
      tb('1100', '40300000', -100, -200, -200),
    ]
    const c = intercompanyControl(rows, toEur)
    const loan = c.pairs.find((p) => p.id === 'loan')!
    expect(loan).toMatchObject({ recordedEur: 500 - 600, afterEur: 0, truthEur: 0, tone: 'ok' })
    const invoices = c.pairs.find((p) => p.id === 'invoices')!
    expect(invoices).toMatchObject({ afterEur: 700, truthEur: 700, tone: 'ok' })
    expect(c.tone).toBe('ok')
  })

  it('requires a zero net without golden, within 1 €', () => {
    const c = intercompanyControl([tb('1000', '55200000', 1_000, 1_050), tb('1100', '55200000', -1_000, -1_000)], toEur)
    expect(c.pairs.find((p) => p.id === 'pooling')).toMatchObject({ afterEur: 50, truthEur: null, tone: 'ok' })
    const off = intercompanyControl([tb('1000', '55200000', 1_000, 1_500), tb('1100', '55200000', -1_000, -1_000)], toEur)
    expect(off.tone).toBe('warn')
  })
})

describe('deliveryControl', () => {
  const file = (task: TaskKey, extra: Partial<FileValidation> = {}): FileValidation => ({
    task,
    present: true,
    rows: 1,
    expected: 1,
    missingKeys: [],
    duplicateKeys: [],
    extraKeys: [],
    unbalancedEntries: [],
    nonIntegerAmounts: 0,
    unknownAccounts: [],
    invalidValues: [],
    errors: [],
    warnings: [],
    ...extra,
  })
  const report = (ok: boolean, overrides: Partial<Record<TaskKey, Partial<FileValidation>>> = {}): ValidationReport => ({
    ok,
    files: Object.fromEntries(TASK_KEYS.map((k) => [k, file(k, overrides[k])])) as ValidationReport['files'],
  })

  it('counts errors, warnings and missing files', () => {
    expect(deliveryControl(report(true))).toEqual({ tone: 'ok', errors: 0, warnings: 0, missingFiles: [] })
    const bad = deliveryControl(report(false, { ic: { present: false, errors: ['Falta ic.jsonl'] }, ap: { warnings: ['x'] } }))
    expect(bad).toEqual({ tone: 'danger', errors: 1, warnings: 1, missingFiles: ['ic'] })
  })
})

describe('mosaicRows', () => {
  it('groups by task in pipeline order and sorts by status', () => {
    const items = [item('close', 'ACCRUAL', 'AUTO'), item('ap', 'HOLD', 'BLOCKED'), item('ap', 'POST', 'AUTO'), item('ap', 'POST', 'NEEDS_HUMAN')]
    const rows = mosaicRows(items)
    expect(rows.map((r) => r.task)).toEqual(['ap', 'ar_billing', 'bank_rec', 'ar_cash', 'ic', 'close'])
    expect(rows[0].items.map((i) => i.status)).toEqual(['AUTO', 'NEEDS_HUMAN', 'BLOCKED'])
    expect(rows[5].items).toHaveLength(1)
  })
})
