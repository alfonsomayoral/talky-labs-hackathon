// @vitest-environment node
import type { ApRow, BankRecRow, RunBundle } from '@/domain/types'
import { AP_CASCADE } from '@/domain/catalog/policy'
import { devPhase, goldenRun, loadCore, loadGolden } from '../test-utils/phase'
import { entryImbalance } from '../ledger/entries'
import { deriveAttention } from './attention'
import { deriveRun } from './deriveRun'
import { synthesizeEvents } from './events'
import { deriveItems, itemEntries } from './items'

const fixture = await devPhase()

describe.skipIf(!fixture)('derive on golden (phase_dev)', () => {
  const golden = fixture ? loadGolden(fixture) : null!
  const core = fixture ? loadCore(fixture, golden) : null!
  const run: RunBundle = fixture ? goldenRun(golden) : null!
  const items = fixture ? deriveItems(core, run) : []
  const byTask = (t: string) => items.filter((i) => i.task === t)
  const apRow = (pred: (r: ApRow) => boolean) => run.deliverables.ap.find(pred)!

  it('creates one item per unit of work', () => {
    const bankUnits = (golden.deliverables.bank_rec as BankRecRow[]).reduce(
      (s, r) => s + r.matches.length + r.unmatched_bank.length + r.unmatched_book.length,
      0,
    )
    expect(byTask('ap')).toHaveLength(305)
    expect(byTask('ar_billing')).toHaveLength(26)
    expect(byTask('ar_cash')).toHaveLength(32)
    expect(byTask('bank_rec')).toHaveLength(bankUnits)
    expect(byTask('ic')).toHaveLength(5)
    const closeKeys = new Set(golden.deliverables.close.map((r) => `${r.type}/${r.company}/${String(r.vendor ?? r.invoice ?? r.item ?? r.customer ?? r.billing_item)}`))
    expect(byTask('close')).toHaveLength(closeKeys.size)
    expect(new Set(items.map((i) => i.id)).size).toBe(items.length)
  })

  it('assigns statuses per PLAN §5', () => {
    const status = (id: string) => items.find((i) => i.id === id)?.status
    const hold = apRow((r) => r.decision === 'HOLD')
    const post = apRow((r) => r.decision === 'POST')
    expect(status(`ap:${hold.doc_id}`)).toBe('BLOCKED')
    expect(status(`ap:${post.doc_id}`)).toBe('AUTO')
    expect(status('ar_billing:BILL-CV-OB-2100-2503-202607')).toBe('BLOCKED')
    expect(status('ic:1000-1200/POOLING_NOT_BOOKED')).toBe('OPEN')
    expect(status('ic:1000-3100/INTEREST_DAY_COUNT')).toBe('AUTO')
    const outstanding = byTask('bank_rec').find((i) => i.outcome === 'OUTSTANDING_PAYMENT')!
    expect(outstanding.status).toBe('OPEN')
    expect(byTask('bank_rec').filter((i) => i.outcome === 'BANK_FEE_NOT_BOOKED').every((i) => i.status === 'AUTO')).toBe(true)
  })

  it('carries the entries, their debit as tbImpact and evidence', () => {
    const cert = items.find((i) => i.id === 'ap:API004128')!
    const entries = itemEntries(core, run, cert.id)
    expect(entries).toHaveLength(1)
    expect(entries[0].lines).toHaveLength(7)
    expect(entryImbalance(entries[0]).size).toBe(0)
    expect(cert.tbImpact).toBe(entries[0].lines.reduce((s, l) => s + l.debit, 0))
    expect(cert.evidence.some((e) => e.kind === 'doc' && e.path.startsWith('inbox/ap/API004128/'))).toBe(true)
    expect(cert.policyRefs).toContain('§2.2.5')
    // Every bank adjustment lands on exactly one item.
    const adjDebit = (golden.deliverables.bank_rec as BankRecRow[]).reduce(
      (s, r) => s + r.adjustments.reduce((a, x) => a + x.lines.reduce((b, l) => b + l.debit, 0), 0),
      0,
    )
    expect(byTask('bank_rec').reduce((s, i) => s + i.tbImpact, 0)).toBe(adjDebit)
    expect(byTask('bank_rec').some((i) => i.key.includes('/adj-'))).toBe(false)
  })

  it('flags a changed IBAN as P0 fraud and sorts attention by priority', () => {
    const attention = deriveAttention(core, run, items)
    const fraudDocs = run.deliverables.ap.filter((r) => r.reasons.includes('BANK_DETAILS_CHANGED')).map((r) => `ap:${r.doc_id}`)
    expect(fraudDocs.length).toBeGreaterThan(0)
    for (const id of fraudDocs) {
      expect(attention.find((a) => a.item === id)).toMatchObject({ priority: 'P0', kind: 'FRAUD_SIGNAL', derived: true })
    }
    const order = attention.map((a) => a.priority)
    expect([...order].sort()).toEqual(order)
    expect(attention.some((a) => a.kind === 'MATERIAL_UNEXPLAINED' && a.priority === 'P0')).toBe(false)
    expect(attention.find((a) => a.item === 'ic:1000-1200/POOLING_NOT_BOOKED')).toMatchObject({ priority: 'P1', kind: 'CROSS_TASK' })
    expect(attention.find((a) => a.item === 'ar_billing:BILL-CV-OB-2100-2503-202607')).toMatchObject({ priority: 'P2' })
  })

  it('synthesizes the §2.2 cascade for a HOLD: PASS until the failing check, then DECIDE', () => {
    const hold = apRow((r) => r.decision === 'HOLD' && r.reasons[0] === 'QTY_NOT_RECEIVED')
    const item = items.find((i) => i.id === `ap:${hold.doc_id}`)!
    const events = synthesizeEvents(core, run, [item])
    const failAt = AP_CASCADE.findIndex((s) => s.code === 'QTY_NOT_RECEIVED')
    expect(events.map((e) => e.step)).toEqual([...AP_CASCADE.slice(0, failAt + 1).map((s) => s.step), 'decision'])
    expect(events.slice(0, failAt).every((e) => e.kind === 'CHECK' && e.result === 'PASS')).toBe(true)
    expect(events[failAt]).toMatchObject({ kind: 'CHECK', result: 'FAIL', policy_ref: '§2.2.3' })
    expect(events.at(-1)).toMatchObject({ kind: 'DECIDE' })
    expect(events.map((e) => e.seq)).toEqual(events.map((_, i) => i + 1))
    expect(events.every((e) => e.ts === run.createdAt && e.duration_ms === undefined)).toBe(true)
  })

  it('synthesizes CLASSIFY for NOT_INVOICE and POST for posted documents', () => {
    const notInvoice = apRow((r) => r.decision === 'NOT_INVOICE')
    const ev1 = synthesizeEvents(core, run, [items.find((i) => i.id === `ap:${notInvoice.doc_id}`)!])
    expect(ev1.map((e) => e.kind)).toEqual(['CLASSIFY', 'DECIDE'])
    const ev2 = synthesizeEvents(core, run, [items.find((i) => i.id === 'ap:API004128')!])
    expect(ev2.filter((e) => e.kind === 'CHECK').every((e) => e.result === 'PASS')).toBe(true)
    expect(ev2.slice(-2).map((e) => e.kind)).toEqual(['DECIDE', 'POST'])
  })

  it('derives the whole run: golden scores 100 and validates', () => {
    const d = deriveRun(core, run, null)
    expect(d.score?.total).toBe(100)
    expect(Object.values(d.score!.perItem).every((s) => s.exact)).toBe(true)
    expect(d.validation.ok).toBe(true)
    expect(d.eventsSynthesized).toBe(true)
    expect(d.trialBalance).toBeNull()
    expect(d.stats.items).toBe(items.length)
    expect(d.stats.attention.count).toBe(d.attention.length)
    expect(d.items.filter((i) => i.status === 'NEEDS_HUMAN').every((i) => d.attention.some((a) => a.item === i.id))).toBe(true)
    const withTb = deriveRun(core, run, golden.trialBalanceRecorded)
    expect(withTb.trialBalance?.gapAfter).toBe(0)
    expect(withTb.trialBalance?.score).toBe(1)
  })
})

describe.skipIf(!fixture)('derive on malformed deliverables', () => {
  it('does not throw and reports the problems', () => {
    const golden = loadGolden(fixture!)
    const core = { ...loadCore(fixture!, null) }
    const run = goldenRun(golden)
    const junk = {
      ap: [{ doc_id: 'X1' }, { doc_id: 'X2', decision: 'HOLD', reasons: 'PRICE_VARIANCE', journal_entry: { lines: [null, { account: 1, debit: '5' }] } }],
      ar_billing: [{ billing_item: 'B1', invoice: {} }],
      ar_cash: [{ bank_line: 'BL0000085', applications: null, adjustment: [{ account: '55500000', debit: 1 }] }],
      bank_rec: [{ account: 'BIN-1000', matches: [{}], unmatched_bank: [{ bank_line: null }], adjustments: [{ category: 'BANK_ERROR', lines: 'x' }] }],
      ic: [{ pair: null, cause: 7 }],
      close: [{ type: 'ACCRUAL' }, { type: 'ACCRUAL', amount: 'abc', journal_entry: [] }],
    }
    const d = deriveRun(core, { ...run, deliverables: junk as never }, [])
    expect(d.score).toBeNull()
    expect(d.validation.ok).toBe(false)
    expect(d.items.length).toBeGreaterThan(0)
    expect(d.attention.some((a) => a.kind === 'MATERIAL_UNEXPLAINED' && a.priority === 'P0')).toBe(true)
    expect(d.trialBalance).toMatchObject({ score: null, gapAfter: null })
  })
})
