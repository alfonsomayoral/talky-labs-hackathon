// @vitest-environment node
import { TASK_KEYS, type TaskKey } from '@/domain/types'
import { deriveRun } from '@/engine'
import { devPhase, goldenRun, loadCore, loadGolden } from '@/engine/test-utils/phase'
import { findFlowFilter, flowIssues, processFlow, type ProcessFlow } from './processFlow'
import { fixtureCore, fixtureRun } from './testing/fixture'

const count = (flow: ProcessFlow, id: string) => {
  const n = flow.nodes.find((x) => x.id === `${flow.task}/${id}`)
  if (n) return n.count
  for (const x of flow.nodes) {
    const sub = x.breakdown.find((b) => b.id === `${flow.task}/${id}`)
    if (sub) return sub.count
  }
  return undefined
}

describe('processFlow on a small fixture', () => {
  const core = fixtureCore()
  const run = fixtureRun()
  const derived = deriveRun(core, run, null)
  const flow = (task: TaskKey) => processFlow(task, derived, core, run)

  it.each(TASK_KEYS)('%s: counts are conserved through links and breakdowns', (task) => {
    expect(flowIssues(flow(task))).toEqual([])
  })

  it('AP follows the §2.2 cascade: first failing check decides', () => {
    const f = flow('ap')
    expect(count(f, 'received')).toBe(8)
    expect(count(f, 'not_invoice')).toBe(1)
    expect(count(f, 'not_invoice/UPDATE_BANK_DETAILS')).toBe(1)
    expect(count(f, 'invoices')).toBe(7)
    expect(count(f, 'duplicate')).toBe(1)
    expect(count(f, 'reject')).toBe(2)
    expect(count(f, 'reject/ISP_NOT_APPLIED')).toBe(1)
    // VAT rate comes before withholding in the cascade.
    expect(count(f, 'reject/VAT_RATE_INCORRECT')).toBe(1)
    expect(count(f, 'reject/WITHHOLDING_MISSING')).toBeUndefined()
    expect(count(f, 'hold/BANK_DETAILS_CHANGED')).toBe(1)
    expect(count(f, 'payment_block')).toBe(1)
    expect(count(f, 'post')).toBe(2)
    expect(count(f, 'post/CREDIT_NOTE')).toBe(1)
    const post = f.nodes.find((n) => n.id === 'ap/post')!
    expect(post.annotation).toBe('1 con pago al factor')
    expect(post.filter.items).toEqual(new Set(['ap:A1', 'ap:A8']))
    expect(f.columns).toHaveLength(6)
    expect(post.section).toBe('§2.2.5')
  })

  it('AR billing splits invoice / pending approval and invoices by contract type', () => {
    const f = flow('ar_billing')
    expect(count(f, 'invoice')).toBe(2)
    expect(count(f, 'skip')).toBe(1)
    expect(count(f, 'type/OBRA_CERTIFICATION')).toBe(1)
    expect(count(f, 'type/SERVICE_MONTHLY')).toBe(1)
    expect(f.nodes.find((n) => n.id === 'ar_billing/invoice')?.annotation).toBe('1 factura por FACe con DIR3')
  })

  it('AR cash: customer → application → differences', () => {
    const f = flow('ar_cash')
    expect(count(f, 'customer')).toBe(2)
    expect(count(f, 'non_customer')).toBe(1)
    expect(count(f, 'application/single')).toBe(1)
    expect(count(f, 'application/grouped')).toBe(1)
    expect(count(f, 'application/none')).toBe(1)
    expect(count(f, 'no_difference')).toBe(1)
    expect(count(f, 'difference')).toBe(2)
    expect(count(f, 'difference/PENALTY')).toBe(1)
    expect(count(f, 'difference/NON_CUSTOMER')).toBe(1)
  })

  it('bank: matches by shape, unmatched by side and category, adjusted or not', () => {
    const f = flow('bank_rec')
    expect(count(f, 'items')).toBe(4)
    expect(count(f, 'matched')).toBe(2)
    expect(count(f, 'matched/1x1')).toBe(1)
    expect(count(f, 'matched/1xN')).toBe(1)
    expect(count(f, 'unmatched_bank/BANK_FEE_NOT_BOOKED')).toBe(1)
    expect(count(f, 'unmatched_book/OUTSTANDING_PAYMENT')).toBe(1)
    expect(count(f, 'clean')).toBe(2)
    expect(count(f, 'adjusted')).toBe(1)
    expect(count(f, 'not_adjusted')).toBe(1)
    expect(f.nodes[0].annotation).toBe('3 líneas del extracto · 4 apuntes del libro · 1 cuenta')
  })

  it('IC: causes, clean pairs and responsible company', () => {
    const f = flow('ic')
    expect(count(f, 'differences')).toBe(2)
    expect(count(f, 'clean_pairs')).toBe(1)
    expect(count(f, 'cause/INTEREST_DAY_COUNT')).toBe(1)
    expect(count(f, 'adjusted/3100')).toBe(1)
    expect(count(f, 'not_adjusted')).toBe(1)
  })

  it('close: one node per type of tasks/close.json, amounts in EUR', () => {
    const f = flow('close')
    expect(count(f, 'type/ACCRUAL')).toBe(1)
    expect(count(f, 'type/PREPAID')).toBe(0)
    const fx = f.nodes.find((n) => n.id === 'close/type/FX_REVAL')!
    // 2.000,00 MXN at 20 MXN/EUR.
    expect(fx.amount).toBe(10000)
  })

  it('finds a filter by node or breakdown id', () => {
    const f = flow('ap')
    expect(findFlowFilter(f, 'ap/reject/ISP_NOT_APPLIED')?.items).toEqual(new Set(['ap:A2']))
    expect(findFlowFilter(f, 'ap/nope')).toBeNull()
  })
})

const fixture = await devPhase()

describe.skipIf(!fixture)('processFlow on golden (phase_dev)', () => {
  const golden = fixture ? loadGolden(fixture) : null!
  const core = fixture ? loadCore(fixture, golden) : null!
  const run = fixture ? goldenRun(golden) : null!
  const derived = fixture ? deriveRun(core, run, null) : null!

  it.each(TASK_KEYS)('%s: every item reaches the map and counts add up', (task) => {
    const f = processFlow(task, derived, core, run)
    expect(flowIssues(f)).toEqual([])
    expect(f.total.count).toBe(derived.items.filter((i) => i.task === task).length)
  })

  it('AP: 305 received → 12 not invoices, 14 duplicates, 18 rejected, 19 held, 242 posted', () => {
    const f = processFlow('ap', derived, core, run)
    expect(count(f, 'received')).toBe(305)
    expect(count(f, 'not_invoice')).toBe(12)
    expect(count(f, 'duplicate')).toBe(14)
    expect(count(f, 'reject')).toBe(18)
    expect(count(f, 'hold')).toBe(19)
    expect(count(f, 'hold/BANK_DETAILS_CHANGED')).toBe(2)
    expect(count(f, 'payment_block')).toBe(0)
    expect(count(f, 'post')).toBe(242)
    expect(f.nodes.find((n) => n.id === 'ap/post')?.annotation).toBe('1 con pago al factor')
  })

  it('AR billing, AR cash, IC and close match the golden shapes', () => {
    expect(count(processFlow('ar_billing', derived, core, run), 'skip')).toBe(1)
    const cash = processFlow('ar_cash', derived, core, run)
    expect(count(cash, 'non_customer')).toBe(2)
    expect(count(cash, 'difference/FACTORED_MISDIRECTED')).toBe(2)
    const ic = processFlow('ic', derived, core, run)
    expect(count(ic, 'differences')).toBe(5)
    expect(count(ic, 'clean_pairs')).toBe(3)
    expect(count(ic, 'not_adjusted')).toBe(1)
    const close = processFlow('close', derived, core, run)
    expect(count(close, 'type/ACCRUAL')).toBe(new Set(golden.deliverables.close.filter((r) => r.type === 'ACCRUAL').map((r) => `${r.company}/${r.vendor}`)).size)
  })

  it('bank: N:1 and 1:N matches show up as shapes', () => {
    const f = processFlow('bank_rec', derived, core, run)
    expect(count(f, 'matched/Nx1')).toBe(1)
    expect(count(f, 'matched/1xN')).toBe(7)
    expect(count(f, 'unmatched_bank/BANK_FEE_NOT_BOOKED')).toBe(31)
  })
})
