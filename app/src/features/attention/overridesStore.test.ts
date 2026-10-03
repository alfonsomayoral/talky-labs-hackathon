import { useOverridesStore } from './overridesStore'

const store = () => useOverridesStore.getState()
const base = { runId: 'r1', item: 'ap:API1', attention_id: 'att-1', decision: 'HOLD' } as const

beforeEach(() => {
  localStorage.clear()
  useOverridesStore.setState({ byRun: {} })
})

describe('overridesStore', () => {
  it('adds one override per (item, attention_id) and replaces it on a new decision', () => {
    store().add({ ...base, action: 'ACCEPT' })
    store().add({ ...base, action: 'CHOOSE_ALTERNATIVE', decision: 'POST' })
    store().add({ ...base, attention_id: 'att-2', action: 'SNOOZE', decision: null })
    expect(store().forRun('r1').map((o) => [o.attention_id, o.action, o.decision])).toEqual([
      ['att-1', 'CHOOSE_ALTERNATIVE', 'POST'],
      ['att-2', 'SNOOZE', null],
    ])
    expect(store().forRun('r1')[0]).toMatchObject({ user: 'revisor', runId: 'r1' })
    expect(store().forRun('other')).toEqual([])
  })

  it('keeps a saved note when a later decision does not bring one', () => {
    store().add({ ...base, action: 'NOTE', decision: null, note: 'Llamado al proveedor' })
    store().add({ ...base, action: 'ACCEPT' })
    expect(store().forRun('r1')).toMatchObject([{ action: 'ACCEPT', note: 'Llamado al proveedor' }])
    store().add({ ...base, action: 'ACCEPT', note: null })
    expect(store().forRun('r1')[0].note).toBeNull()
  })

  it('removes one attention entry or the whole item', () => {
    store().add({ ...base, action: 'ACCEPT' })
    store().add({ ...base, attention_id: 'att-2', action: 'ACCEPT' })
    store().add({ ...base, item: 'ap:API2', attention_id: 'att-3', action: 'ACCEPT' })
    store().remove('r1', 'ap:API1', 'att-1')
    expect(store().forRun('r1').map((o) => o.attention_id)).toEqual(['att-2', 'att-3'])
    store().remove('r1', 'ap:API1')
    expect(store().forRun('r1').map((o) => o.attention_id)).toEqual(['att-3'])
  })

  it('persists to localStorage', () => {
    store().add({ ...base, action: 'ACCEPT' })
    expect(JSON.parse(localStorage.getItem('kalmora.overrides.v1')!).r1).toHaveLength(1)
  })

  it('exports one CONTRACT §3 object per line', () => {
    store().add({ ...base, action: 'ACCEPT', note: 'ok' })
    store().add({ ...base, item: 'ap:API2', attention_id: null, action: 'SNOOZE', decision: null })
    const lines = store().toJsonl('r1').split('\n').map((l) => JSON.parse(l) as Record<string, unknown>)
    expect(lines).toHaveLength(2)
    expect(Object.keys(lines[0])).toEqual(['attention_id', 'item', 'action', 'decision', 'note', 'user', 'ts'])
    expect(lines[0]).toMatchObject({ attention_id: 'att-1', item: 'ap:API1', action: 'ACCEPT', decision: 'HOLD', note: 'ok', user: 'revisor' })
    expect(lines[1]).toMatchObject({ attention_id: null, item: 'ap:API2', action: 'SNOOZE', decision: null })
    expect(store().toJsonl('empty')).toBe('')
  })
})
