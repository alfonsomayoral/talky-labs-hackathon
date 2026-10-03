// @vitest-environment node
import type { AttentionItem, WorkItem } from '@/domain/types'
import type { Override } from './overridesStore'
import {
  buildRows,
  decisionOptions,
  familyOf,
  groupByPriority,
  matchesFilters,
  NO_FILTERS,
  overrideFor,
  policyDescription,
  similarRows,
  totalsByCurrency,
} from './attentionModel'

const att = (over: Partial<AttentionItem> & Pick<AttentionItem, 'attention_id' | 'item'>): AttentionItem => ({
  kind: 'POLICY_EXCEPTION',
  priority: 'P2',
  title: 'Retener: Desviación de precio',
  impact: 1000,
  affects_tb: false,
  policy_ref: '§2.2.3',
  recommendation: { decision: 'HOLD', reasons: ['PRICE_VARIANCE'] },
  alternatives: [],
  ...over,
})

const work = (id: string, over: Partial<WorkItem> = {}): WorkItem => ({
  id,
  task: id.split(':')[0] as WorkItem['task'],
  key: id.split(':')[1],
  company: '1100',
  title: id,
  counterparty: 'Proveedor Uno',
  amount: 1000,
  currency: 'EUR',
  date: null,
  status: 'BLOCKED',
  outcome: 'HOLD',
  reasons: [],
  confidence: null,
  provenance: 'RULE',
  policyRefs: [],
  evidence: [],
  tbImpact: 0,
  rowIndex: 0,
  ...over,
})

const override = (item: string, attention_id: string | null, action: Override['action'], decision: string | null = null): Override => ({
  runId: 'r1',
  item,
  attention_id,
  action,
  decision,
  note: null,
  user: 'revisor',
  ts: '2026-10-03T10:00:00Z',
})

const index = (items: WorkItem[]) => new Map(items.map((i) => [i.id, i]))

describe('families', () => {
  it('splits the world that must act from the agent that doubts, fraud apart', () => {
    expect(familyOf('FRAUD_SIGNAL')).toBe('fraud')
    expect(['POLICY_EXCEPTION', 'MASTER_DATA', 'CROSS_TASK'].map((k) => familyOf(k as AttentionItem['kind']))).toEqual(['world', 'world', 'world'])
    expect(['AGENT_DOUBT', 'ESTIMATE', 'MATERIAL_UNEXPLAINED', 'DATA_QUALITY'].map((k) => familyOf(k as AttentionItem['kind']))).toEqual([
      'doubt',
      'doubt',
      'doubt',
      'doubt',
    ])
  })
})

describe('buildRows + groupByPriority', () => {
  it('orders P0 → P3 and, inside a priority, by expected loss when confidence exists', () => {
    const attention = [
      att({ attention_id: 'a', item: 'ap:A', priority: 'P2', impact: 1000 }),
      att({ attention_id: 'b', item: 'ap:B', priority: 'P0', impact: 10 }),
      // (1 − 0.5) × 4000 = 2000 > 1000
      att({ attention_id: 'c', item: 'ap:C', priority: 'P2', impact: 4000, confidence: 0.5 }),
      // (1 − 0.99) × 50000 = 500 < 1000
      att({ attention_id: 'd', item: 'ap:D', priority: 'P2', impact: 50000, confidence: 0.99 }),
    ]
    const groups = groupByPriority(buildRows(attention, new Map(), []))
    expect(groups.map((g) => g.priority)).toEqual(['P0', 'P2'])
    expect(groups[1].rows.map((r) => r.key)).toEqual(['c', 'a', 'd'])
  })

  it('sums impacts per currency, EUR first, instead of mixing MXN into euros', () => {
    const items = [work('ap:A'), work('ap:M', { company: '3100', currency: 'MXN' })]
    const rows = buildRows([att({ attention_id: 'm', item: 'ap:M', impact: 500 }), att({ attention_id: 'a', item: 'ap:A', impact: 200 })], index(items), [])
    expect(totalsByCurrency(rows)).toEqual([
      { currency: 'EUR', cents: 200 },
      { currency: 'MXN', cents: 500 },
    ])
  })

  it('marks accepted and alternative rows as resolved, snoozed apart, notes still pending', () => {
    const attention = ['a', 'b', 'c', 'd'].map((id) => att({ attention_id: id, item: `ap:${id}` }))
    const overrides = [override('ap:a', 'a', 'ACCEPT', 'HOLD'), override('ap:b', 'b', 'CHOOSE_ALTERNATIVE', 'POST'), override('ap:c', 'c', 'SNOOZE'), override('ap:d', 'd', 'NOTE')]
    const res = Object.fromEntries(buildRows(attention, new Map(), overrides).map((r) => [r.key, r.resolution]))
    expect(res).toEqual({ a: 'resolved', b: 'resolved', c: 'snoozed', d: 'pending' })
  })
})

describe('overrideFor', () => {
  it('matches item and attention_id, with item-wide overrides as fallback', () => {
    const a = att({ attention_id: 'x1', item: 'ar_cash:BL1' })
    expect(overrideFor([override('ar_cash:BL1', 'x2', 'ACCEPT')], a)).toBeNull()
    expect(overrideFor([override('ar_cash:BL1', null, 'SNOOZE')], a)?.action).toBe('SNOOZE')
    expect(overrideFor([override('ar_cash:BL1', null, 'SNOOZE'), override('ar_cash:BL1', 'x1', 'ACCEPT')], a)?.action).toBe('ACCEPT')
    expect(overrideFor([override('ar_cash:BL2', 'x1', 'ACCEPT')], a)).toBeNull()
  })
})

describe('similarRows', () => {
  const rows = buildRows(
    [
      att({ attention_id: 't', item: 'ap:T' }),
      att({ attention_id: 'same', item: 'ap:S', recommendation: { decision: 'HOLD', reasons: ['PRICE_VARIANCE'] } }),
      att({ attention_id: 'reason', item: 'ap:R', recommendation: { decision: 'HOLD', reasons: ['QTY_NOT_RECEIVED'] } }),
      att({ attention_id: 'decision', item: 'ap:D', recommendation: { decision: 'REJECT', reasons: ['PRICE_VARIANCE'] } }),
      att({ attention_id: 'kind', item: 'ap:K', kind: 'AGENT_DOUBT' }),
      att({ attention_id: 'task', item: 'ar_cash:BL1' }),
      att({ attention_id: 'done', item: 'ap:Z' }),
    ],
    new Map(),
    [override('ap:Z', 'done', 'ACCEPT', 'HOLD')],
  )
  const target = rows.find((r) => r.key === 't')!

  it('needs the same task, kind, decision and reasons, and only pending rows', () => {
    expect(similarRows(target, rows).map((r) => r.key)).toEqual(['same'])
  })

  it('ignores reason order and never matches without a recommended decision', () => {
    const [x, y, none] = buildRows(
      [
        att({ attention_id: 'x', item: 'ap:X', recommendation: { decision: 'REJECT', reasons: ['A', 'B'] } }),
        att({ attention_id: 'y', item: 'ap:Y', recommendation: { decision: 'REJECT', reasons: ['B', 'A'] } }),
        att({ attention_id: 'n', item: 'ap:N', recommendation: null }),
      ],
      new Map(),
      [],
    )
    expect(similarRows(x, [x, y, none]).map((r) => r.key)).toEqual(['y'])
    expect(similarRows(none, [x, y, none])).toEqual([])
  })
})

describe('matchesFilters', () => {
  const [row] = buildRows([att({ attention_id: 'a', item: 'ap:API004151', title: 'IBAN distinto', kind: 'FRAUD_SIGNAL', priority: 'P0' })], index([work('ap:API004151', { counterparty: 'Construcciones Peñalara' })]), [])

  it('combines facets and accent-insensitive text search', () => {
    expect(matchesFilters(row, NO_FILTERS)).toBe(true)
    expect(matchesFilters(row, { ...NO_FILTERS, priority: ['P0'], task: ['ap'], company: ['1100'] })).toBe(true)
    expect(matchesFilters(row, { ...NO_FILTERS, kind: ['ESTIMATE'] })).toBe(false)
    expect(matchesFilters(row, { ...NO_FILTERS, company: ['3100'] })).toBe(false)
    expect(matchesFilters(row, { ...NO_FILTERS, query: 'penalara' })).toBe(true)
    expect(matchesFilters(row, { ...NO_FILTERS, query: '004151' })).toBe(true)
    expect(matchesFilters(row, { ...NO_FILTERS, query: 'fraude' })).toBe(true)
    expect(matchesFilters(row, { ...NO_FILTERS, query: 'nada' })).toBe(false)
  })
})

describe('decisionOptions + policyDescription', () => {
  it('puts the agent alternatives first (by p) and leaves the recommended decision out', () => {
    const [row] = buildRows(
      [att({ attention_id: 'a', item: 'ap:A', alternatives: [{ decision: 'REJECT', p: 0.1 }, { decision: 'POST', p: 0.3 }] })],
      new Map(),
      [],
    )
    const { alternatives, others } = decisionOptions(row)
    expect(alternatives.map((x) => [x.decision, x.label, x.p])).toEqual([
      ['POST', 'Contabilizar', 0.3],
      ['REJECT', 'Rechazar', 0.1],
    ])
    expect(others.map((x) => x.decision)).not.toContain('HOLD')
    expect(others.map((x) => x.decision)).not.toContain('POST')
    expect(others.map((x) => x.decision)).toContain('DUPLICATE')
  })

  it('describes the cited section from the reason first', () => {
    const [row] = buildRows([att({ attention_id: 'a', item: 'ap:A', recommendation: { decision: 'HOLD', reasons: ['BANK_DETAILS_CHANGED'] } })], new Map(), [])
    expect(policyDescription(row)).toMatch(/IBAN/)
  })
})
