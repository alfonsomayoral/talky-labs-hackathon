// Sidebar badge: attention entries still waiting for a person (resolved or snoozed ones drop out).
import type { AttentionItem } from '@/domain/types'
import { overrideFor, resolutionOf } from '@/features/attention/attentionModel'
import type { Override } from '@/features/attention/overridesStore'

export function pendingAttention(attention: readonly AttentionItem[], overrides: readonly Override[]): { count: number; urgent: boolean } {
  const byItem = new Map<string, Override[]>()
  for (const o of overrides) byItem.set(o.item, [...(byItem.get(o.item) ?? []), o])
  let count = 0
  let urgent = false
  for (const a of attention) {
    if (resolutionOf(overrideFor(byItem.get(a.item) ?? [], a)) !== 'pending') continue
    count++
    if (a.priority === 'P0') urgent = true
  }
  return { count, urgent }
}
