import { buildItems, sortRows } from './model'

interface Row {
  id: string
  amount: number | null
  status: string
}

const rows: Row[] = [
  { id: 'API10', amount: 300, status: 'AUTO' },
  { id: 'API2', amount: null, status: 'BLOCKED' },
  { id: 'API1', amount: 100, status: 'AUTO' },
  { id: 'Ábaco', amount: 100, status: 'OPEN' },
]

describe('sortRows', () => {
  it('sorts numbers and keeps ties stable', () => {
    expect(sortRows(rows, (r) => r.amount, 'asc').map((r) => r.id)).toEqual(['API1', 'Ábaco', 'API10', 'API2'])
  })

  it('keeps nulls last when descending', () => {
    expect(sortRows(rows, (r) => r.amount, 'desc').map((r) => r.id)).toEqual(['API10', 'API1', 'Ábaco', 'API2'])
  })

  it('compares strings naturally and accent-insensitively', () => {
    expect(sortRows(rows, (r) => r.id, 'asc').map((r) => r.id)).toEqual(['Ábaco', 'API1', 'API2', 'API10'])
  })
})

describe('buildItems', () => {
  it('returns plain rows without grouping', () => {
    expect(buildItems(rows, undefined, undefined, new Set())).toHaveLength(4)
  })

  it('groups in the given order, then alphabetically, keeping row order', () => {
    const items = buildItems(rows, (r) => r.status, ['OPEN', 'AUTO'], new Set())
    const shape = items.map((it) => (it.kind === 'group' ? `#${it.key}` : it.row.id))
    expect(shape).toEqual(['#OPEN', 'Ábaco', '#AUTO', 'API10', 'API1', '#BLOCKED', 'API2'])
  })

  it('omits rows of collapsed groups but keeps their header and count', () => {
    const items = buildItems(rows, (r) => r.status, undefined, new Set(['AUTO']))
    const auto = items.find((it) => it.kind === 'group' && it.key === 'AUTO')
    expect(auto && auto.kind === 'group' && auto.rows).toHaveLength(2)
    expect(items.filter((it) => it.kind === 'row')).toHaveLength(2)
  })

  it('handles 40k rows quickly', () => {
    const many = Array.from({ length: 40_000 }, (_, i) => ({ id: `R${i}`, amount: (i * 7919) % 10007, status: ['AUTO', 'OPEN', 'BLOCKED'][i % 3] }))
    const t0 = performance.now()
    const items = buildItems(sortRows(many, (r) => r.amount, 'desc'), (r) => r.status, undefined, new Set())
    expect(items).toHaveLength(40_003)
    expect(performance.now() - t0).toBeLessThan(500)
  })
})
