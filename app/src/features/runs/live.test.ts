import type { AgentEvent } from '@/domain/types'
import { createLiveTracker, createPacer } from './live'

let seq = 0
const ev = (item: string, kind: AgentEvent['kind'], result: AgentEvent['result'] = 'PASS'): AgentEvent => ({
  event_id: `e-${++seq}`,
  item,
  seq,
  ts: '2026-10-03T10:00:00Z',
  kind,
  step: 'x',
  result,
  summary: '',
})
const msg = (e: AgentEvent | AgentEvent[]) => ({ type: 'message', data: JSON.stringify(e) })

describe('live tracker', () => {
  it('counts items and decisions per task and completes a task when every item is decided', () => {
    const t = createLiveTracker({ ap: 2, ar_billing: 1, bank_rec: 2 })
    expect(t.snapshot().state).toBe('connecting')
    t.push(msg(ev('ap:A1', 'CHECK', 'FAIL')))
    t.push(msg(ev('ap:A1', 'DECIDE')))
    let s = t.snapshot()
    expect(s.state).toBe('running')
    expect(s.tasks.ap).toMatchObject({ state: 'running', items: 1, decided: 1, done: 1, total: 2, fails: 1, lastItem: 'ap:A1' })
    expect(s.tasks.ar_billing.state).toBe('pending')

    t.push(msg([ev('ap:A2', 'DECIDE'), ev('bank_rec:BIN-1100/BL1', 'DECIDE'), ev('bank_rec:BIN-1100/BL2', 'DECIDE')]))
    s = t.snapshot()
    expect(s.tasks.ap.state).toBe('done')
    // bank_rec progresses by account, not by line.
    expect(s.tasks.bank_rec).toMatchObject({ state: 'running', items: 2, done: 1, total: 2 })
    expect(s.events[0].item).toBe('bank_rec:BIN-1100/BL2')
    expect(s.received).toBe(5)
  })

  it('finishes a task without a known size once the next one in the pipeline starts', () => {
    const t = createLiveTracker({})
    t.push(msg(ev('ic:1000-1200/X', 'DECIDE')))
    expect(t.snapshot().tasks.ic.state).toBe('running')
    t.push(msg(ev('close:ACCRUAL/1', 'DECIDE')))
    const s = t.snapshot()
    expect(s.tasks.ic.state).toBe('done')
    expect(s.tasks.close.state).toBe('running')
  })

  it('ignores malformed messages and unknown items', () => {
    const t = createLiveTracker({})
    t.push({ type: 'message', data: 'not json' })
    t.push(msg(ev('nope:X', 'DECIDE')))
    expect(t.snapshot().received).toBe(0)
  })

  it('marks every task done on `done` and keeps the error only when the stream failed first', () => {
    const t = createLiveTracker({ ap: 5 })
    t.push(msg(ev('ap:A1', 'DECIDE')))
    t.push({ type: 'error', data: 'caída' })
    let s = t.snapshot()
    expect(s.state).toBe('failed')
    expect(s.error).toBe('caída')
    expect(s.tasks.ap.state).toBe('failed')
    expect(s.tasks.close.state).toBe('pending')

    const ok = createLiveTracker({ ap: 5 })
    ok.push(msg(ev('ap:A1', 'DECIDE')))
    ok.push({ type: 'done', data: '' })
    ok.push({ type: 'error', data: 'cerrada' })
    s = ok.snapshot()
    expect(s.state).toBe('done')
    expect(s.error).toBeNull()
    expect(s.tasks.ap.state).toBe('done')
  })
})

describe('pacer', () => {
  const items = (out: { type: string; data: unknown }[]) =>
    out.flatMap((m) => (m.type === 'message' && Array.isArray(m.data) ? (m.data as AgentEvent[]).map((e) => e.item) : [m.type]))

  it('keeps each task on screen for a second before the next one starts, and holds `done` until the end', () => {
    const p = createPacer(1000, 100)
    p.push({ type: 'message', data: [ev('ap:A1', 'DECIDE'), ev('ap:A2', 'DECIDE'), ev('ar_billing:B1', 'DECIDE')] })
    p.push({ type: 'done', data: '' })
    expect(items(p.take(0))).toEqual(['ap:A1'])
    expect(items(p.take(500))).toEqual(['ap:A2'])
    expect(items(p.take(999))).toEqual([])
    expect(items(p.take(1000))).toEqual(['ar_billing:B1'])
    expect(items(p.take(1999))).toEqual([])
    expect(items(p.take(2000))).toEqual(['done'])
  })

  it('spreads a task over its second, and passes empty batches straight through', () => {
    const p = createPacer(1000, 100)
    p.push({ type: 'message', data: JSON.stringify(Array.from({ length: 50 }, (_, i) => ev(`ap:A${i}`, 'DECIDE'))) })
    const first = items(p.take(0)).length
    expect(first).toBeGreaterThan(0)
    expect(first).toBeLessThan(50)
    expect(first + items(p.take(1000)).length).toBe(50)
    p.push({ type: 'message', data: [] })
    expect(p.take(1000)).toEqual([{ type: 'message', data: [] }])
  })
})
