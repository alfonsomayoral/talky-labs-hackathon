import type { AttentionItem } from '@/domain/types'
import type { Override } from '@/features/attention/overridesStore'
import { pendingAttention } from './attentionBadge'

const entry = (item: string, priority: AttentionItem['priority'], attention_id = `${item}#1`): AttentionItem =>
  ({ attention_id, item, kind: 'AGENT_DOUBT', priority, title: item, impact: 100, affects_tb: false })

const override = (item: string, action: Override['action'], attention_id: string | null = `${item}#1`): Override => ({
  runId: 'r1',
  attention_id,
  item,
  action,
  decision: null,
  note: null,
  user: 'revisor',
  ts: '2026-10-03T10:00:00Z',
})

describe('pendingAttention', () => {
  const attention = [entry('ap:A1', 'P0'), entry('ap:A2', 'P1'), entry('ap:A3', 'P2'), entry('ap:A4', 'P3')]

  it('counts everything as pending without overrides', () => {
    expect(pendingAttention(attention, [])).toEqual({ count: 4, urgent: true })
  })

  it('leaves out resolved and snoozed entries; a note keeps it pending', () => {
    const overrides = [override('ap:A1', 'ACCEPT'), override('ap:A2', 'SNOOZE'), override('ap:A3', 'NOTE')]
    expect(pendingAttention(attention, overrides)).toEqual({ count: 2, urgent: false })
  })

  it('applies an item-wide override to every entry of that item', () => {
    const twice = [entry('ap:A1', 'P0', 'x'), entry('ap:A1', 'P1', 'y')]
    expect(pendingAttention(twice, [override('ap:A1', 'CHOOSE_ALTERNATIVE', null)])).toEqual({ count: 0, urgent: false })
  })
})
