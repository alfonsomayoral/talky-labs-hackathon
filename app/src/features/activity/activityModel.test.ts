import { describe, expect, it } from 'vitest'
import type { AgentEvent, WorkItem } from '@/domain/types'
import { applyActivityParams, CLEARED, filterEvents, filterItems, parseActivityParams, type ActivityFilters } from './activityModel'

const item = (id: string, patch: Partial<WorkItem> = {}): WorkItem => {
  const [task, key] = id.split(':') as [WorkItem['task'], string]
  return {
    id,
    task,
    key,
    company: '1100',
    title: key,
    counterparty: null,
    amount: 100,
    currency: 'EUR',
    date: null,
    status: 'AUTO',
    outcome: 'POST',
    reasons: [],
    confidence: null,
    provenance: 'RULE',
    policyRefs: [],
    evidence: [],
    tbImpact: 0,
    rowIndex: 0,
    ...patch,
  }
}

const event = (item: string, seq: number, ts: string, patch: Partial<AgentEvent> = {}): AgentEvent => ({
  event_id: `${item}#${seq}`,
  item,
  seq,
  ts,
  kind: 'CHECK',
  step: 'check',
  result: 'PASS',
  summary: '',
  ...patch,
})

const none = parseActivityParams(new URLSearchParams())

describe('activity URL params', () => {
  it('round-trips every filter and keeps foreign params such as the open item', () => {
    const patch: Partial<ActivityFilters> = { task: 'ap', view: 'timeline', status: ['AUTO', 'BLOCKED'], attention: 'yes', q: 'iban', node: 'hold', kind: ['DECIDE'] }
    const next = applyActivityParams(new URLSearchParams('item=ap:API004128'), patch)
    expect(next.get('item')).toBe('ap:API004128')
    expect(next.get('vista')).toBe('linea')
    expect(next.get('atencion')).toBe('si')
    expect(parseActivityParams(next)).toMatchObject(patch)
  })

  it('drops empty values and ignores unknown tasks', () => {
    const next = applyActivityParams(new URLSearchParams('tarea=ap&estado=AUTO&q=x'), CLEARED)
    expect(next.toString()).toBe('tarea=ap')
    expect(parseActivityParams(new URLSearchParams('tarea=nope')).task).toBeNull()
  })
})

describe('filterItems', () => {
  const items = [
    item('ap:API1', { counterparty: 'Construcciones Álvarez', status: 'BLOCKED', outcome: 'HOLD', reasons: ['BANK_DETAILS_CHANGED'] }),
    item('ap:API2', { company: '1200' }),
    item('ar_cash:BL1', { outcome: 'APPLIED' }),
  ]
  const ctx = { attention: new Set(['ap:API1']), node: null }

  it('matches text without accents across title, counterparty and reasons', () => {
    expect(filterItems(items, { ...none, q: 'alvarez bank_details' }, ctx).map((i) => i.id)).toEqual(['ap:API1'])
  })

  it('combines task, company, outcome and attention filters', () => {
    expect(filterItems(items, { ...none, task: 'ap' }, ctx)).toHaveLength(2)
    expect(filterItems(items, { ...none, company: ['1200'] }, ctx).map((i) => i.id)).toEqual(['ap:API2'])
    expect(filterItems(items, { ...none, outcome: ['ar_cash:APPLIED'] }, ctx).map((i) => i.id)).toEqual(['ar_cash:BL1'])
    expect(filterItems(items, { ...none, attention: 'no' }, ctx)).toHaveLength(2)
  })

  it('keeps only the items of the selected process map node', () => {
    expect(filterItems(items, none, { ...ctx, node: new Set(['ap:API2']) }).map((i) => i.id)).toEqual(['ap:API2'])
  })
})

describe('filterEvents', () => {
  it('filters by task and kind and sorts by time, then by input order', () => {
    const events = [
      event('ap:API2', 1, '2026-07-31T10:00:02Z', { kind: 'DECIDE' }),
      event('ap:API1', 2, '2026-07-31T10:00:01Z', { kind: 'DECIDE' }),
      event('ap:API1', 1, '2026-07-31T10:00:01Z'),
      event('ar_cash:BL1', 1, '2026-07-31T10:00:00Z', { kind: 'DECIDE' }),
    ]
    const taskOf = (id: string) => id.split(':')[0] as WorkItem['task']
    const out = filterEvents(events, { ...none, task: 'ap', kind: ['DECIDE'] }, taskOf)
    expect(out.map((e) => e.event_id)).toEqual(['ap:API1#2', 'ap:API2#1'])
  })
})
