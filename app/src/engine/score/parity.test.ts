// @vitest-environment node
// Parity of the TypeScript scorer with `python3 score.py` on golden and perturbed submissions.

import type { TaskKey } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { devPhase, hasPython, loadGolden, runScorePy, writeSubmission } from '../test-utils/phase'
import { effectiveDeliverables } from '../ledger/entries'
import { scoreTotals } from './score'

type Row = Record<string, unknown>
type Subs = Partial<Record<TaskKey, Row[] | null>>

const fixture = await devPhase()
const ready = fixture !== null && hasPython(fixture.node)

const clone = <T>(x: T): T => structuredClone(x)
const every = (n: number, offset = 0) => (_: unknown, i: number) => i % n === offset
const lines = (je: unknown): Row[] => {
  if (!je) return []
  if (Array.isArray(je)) return je as Row[]
  return ((je as Row).lines as Row[]) ?? []
}

function expectClose(actual: unknown, expected: unknown, path: string) {
  if (typeof expected === 'number') {
    expect(typeof actual, path).toBe('number')
    expect(Math.abs((actual as number) - expected), `${path}: ts=${String(actual)} py=${expected}`).toBeLessThanOrEqual(1e-4)
    return
  }
  if (expected && typeof expected === 'object') {
    expect(actual && typeof actual === 'object', path).toBe(true)
    expect(Object.keys(actual as Row).sort(), path).toEqual(Object.keys(expected).sort())
    for (const k of Object.keys(expected)) expectClose((actual as Row)[k], (expected as Row)[k], `${path}.${k}`)
    return
  }
  expect(actual, path).toEqual(expected)
}

describe.skipIf(!ready)('score.py parity', () => {
  const f = fixture!
  const golden = ready ? loadGolden(f) : null!
  const gold = golden.deliverables as unknown as Record<TaskKey, Row[]>
  const results: { name: string; py: number; ts: number }[] = []
  let tmp = ''

  beforeAll(() => {
    tmp = f.node.fs.mkdtempSync(f.node.path.join(f.node.tmpdir, 'kalmora-parity-'))
  })
  afterAll(() => {
    if (tmp) f.node.fs.rmSync(tmp, { recursive: true, force: true })
    console.table(results)
  })

  function check(name: string, subs: Subs) {
    const dir = f.node.path.join(tmp, name)
    writeSubmission(f.node, dir, subs)
    const py = runScorePy(f, dir)
    const present = Object.fromEntries(TASK_KEYS.map((k) => [k, !!subs[k]])) as Record<TaskKey, boolean>
    const deliverables = Object.fromEntries(TASK_KEYS.map((k) => [k, subs[k] ?? []]))
    const ts = scoreTotals(effectiveDeliverables({ deliverables: deliverables as never, present }), golden)
    results.push({ name, py: py.total as number, ts: ts.total })
    expect(Math.abs(ts.total - (py.total as number)), `total ts=${ts.total} py=${String(py.total)}`).toBeLessThanOrEqual(1e-4)
    for (const k of [...TASK_KEYS, 'trial_balance'] as const) {
      const { score, ...details } = py[k] as Row
      expectClose(ts.tasks[k].score, score, `${k}.score`)
      expectClose(ts.tasks[k].details, details, `${k}.details`)
    }
    return ts
  }

  it('golden as submission scores 100', () => {
    const ts = check('golden', clone(gold))
    expect(ts.total).toBe(100)
  })

  it('empty submission (no files)', () => {
    check('empty', {})
  })

  it('empty files', () => {
    check('empty-files', Object.fromEntries(TASK_KEYS.map((k) => [k, []])) as Subs)
  })

  it('AP decisions flipped (~10%) and reasons changed', () => {
    const s = clone(gold)
    const order = ['POST', 'HOLD', 'REJECT', 'DUPLICATE', 'NOT_INVOICE', 'POST_PAYMENT_BLOCK']
    s.ap.forEach((r, i) => {
      if (i % 10 === 3) r.decision = order[(order.indexOf(r.decision as string) + 1) % order.length]
      if (i % 7 === 2 && (r.reasons as string[]).length) r.reasons = ['PRICE_VARIANCE']
      if (i % 13 === 5) r.duplicate_of = null
      if (i % 17 === 1) delete r.decision
    })
    s.ap.push({ ...s.ap[0], doc_id: 'API999999', decision: 'MYSTERY' })
    check('ap-flipped', s)
  })

  it('journal entries dropped', () => {
    const s = clone(gold)
    s.ap.filter(every(3)).forEach((r) => delete r.journal_entry)
    s.ar_billing.filter(every(2)).forEach((r) => (r.journal_entry = null))
    s.ar_cash.filter(every(4)).forEach((r) => (r.adjustment = []))
    s.close.filter(every(5)).forEach((r) => delete r.journal_entry)
    s.bank_rec.forEach((r) => (r.adjustments = (r.adjustments as Row[]).filter(every(2))))
    check('je-dropped', s)
  })

  it('amounts nudged by 1–5 cents and by large amounts', () => {
    const s = clone(gold)
    const nudges = [1, 2, 3, 5, -2, -4]
    s.ap.forEach((r, i) => {
      lines(r.journal_entry).forEach((l, j) => {
        if ((i + j) % 4 === 0) {
          const d = nudges[(i + j) % nudges.length]
          if ((l.debit as number) > 0) l.debit = (l.debit as number) + d
          else l.credit = (l.credit as number) + d
        }
      })
      if (i % 9 === 0 && typeof r.net === 'number') r.net = (r.net as number) + (i % 2 ? 1 : 2)
      if (i % 11 === 0 && typeof r.gross === 'number') r.gross = (r.gross as number) + 1_000_000
      if (i % 5 === 0) (r.lines as Row[] | undefined)?.forEach((l) => (l.amount = (l.amount as number) - 777))
    })
    s.ar_billing.forEach((r, i) => {
      const inv = r.invoice as Row | undefined
      if (inv && i % 3 === 0) inv.tax = (inv.tax as number) + 1
      if (inv && i % 4 === 1) inv.payable = (inv.payable as number) + 500
    })
    s.ar_cash.forEach((r, i) => {
      ;(r.applications as Row[]).forEach((a) => {
        if (i % 3 === 0) a.amount = (a.amount as number) + 1
      })
      lines(r.adjustment).forEach((l) => {
        if (i % 2 === 0 && (l.debit as number) > 0) l.debit = (l.debit as number) + 3
      })
    })
    s.close.forEach((r, i) => {
      const a = r.amount as number
      if (i % 4 === 0) r.amount = Math.round(a * 1.1) // inside ±15 % for accruals, outside for the rest
      if (i % 4 === 1) r.amount = Math.round(a * 1.3) // partial credit band
      if (i % 4 === 2) r.amount = a * 3 // miss
      if (i % 4 === 3) r.amount = a + 99 // 1 € floor
    })
    check('amounts', s)
  })

  it('bank matches and adjustments removed, ic.jsonl missing, close items added and removed', () => {
    const s: Subs = clone(gold)
    s.bank_rec!.forEach((r, i) => {
      r.matches = (r.matches as Row[]).filter((_, j) => (i + j) % 5 !== 0)
      r.unmatched_bank = (r.unmatched_bank as Row[]).filter((_, j) => j % 3 !== 1).map((x, j) => (j % 4 === 0 ? { ...x, category: 'BANK_ERROR' } : x))
      r.unmatched_book = [...(r.unmatched_book as Row[]), { book_line: `X-${i}#1`, category: 'OUTSTANDING_PAYMENT' }]
      r.adjustments = (r.adjustments as Row[]).slice(1)
    })
    s.ic = null
    s.close = s.close!.filter(every(6, 1)).concat([
      { type: 'ACCRUAL', company: '1100', vendor: 'V199999', amount: 12345, journal_entry: null },
      { type: 'DOUBTFUL_RECLASS', company: '1200', customer: 'C200999', amount: 0 },
      { type: 'BAD_DEBT', company: '1200', customer: 'C200076', amount: 1 },
    ])
    check('bank-ic-close', s)
  })

  it('messy formats: number variants, reversed ic pairs, duplicates, string amounts, wrong partners', () => {
    const s = clone(gold)
    s.ap.forEach((r, i) => {
      if (i % 6 === 0 && typeof r.invoice_number === 'string') r.invoice_number = `00${(r.invoice_number as string).replace(/-/g, '/')}`
      if (i % 8 === 0 && typeof r.net === 'number') r.net = String(r.net)
      if (i % 12 === 0) lines(r.journal_entry).forEach((l) => (l.partner = 'V000000'))
      if (i % 14 === 0) lines(r.journal_entry).forEach((l) => (l.cost_center = 'CC-X'))
      if (i % 15 === 0 && r.payee) r.payee = { type: 'AEAT_EMBARGO' }
    })
    s.ap.push(clone(s.ap[3]), { ...clone(s.ap[4]), decision: 'REJECT' })
    s.ic = s.ic.map((r, i) => (i % 2 ? { ...r, pair: [...(r.pair as string[])].reverse() } : r))
    s.ic.push({ pair: ['1100', '1910'], cause: 'DUPLICATE_POSTING', adjustment: [{ company: '1910', account: '55210000', debit: 100, credit: 0, partner: '1100' }] })
    s.ar_cash.forEach((r, i) => {
      if (i % 5 === 0) r.residuals = [...(r.residuals as Row[]), { type: 'PENALTY', amount: '120' }]
      if (i % 6 === 0) r.customer = null
    })
    s.ar_billing.forEach((r, i) => {
      const inv = r.invoice as Row | undefined
      if (inv?.face && i % 2 === 0) inv.face = { ...(inv.face as Row), organo_gestor: 'L00000000' }
      if (i === 5) r.expected = 'SKIP_PENDING_APPROVAL'
    })
    check('messy', s)
  })
})
