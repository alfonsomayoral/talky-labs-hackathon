// Sidebar badge: attention entries still waiting for a person (resolved or snoozed ones drop out).
import type { AttentionItem } from '@/domain/types'
import { overrideFor, resolutionOf } from '@/features/attention/attentionModel'
import type { Override } from '@/features/attention/overridesStore'

/** Entries no person has resolved or snoozed yet (a note keeps them pending). */
export function pendingAttentionItems(attention: readonly AttentionItem[], overrides: readonly Override[]): AttentionItem[] {
  const byItem = new Map<string, Override[]>()
  for (const o of overrides) byItem.set(o.item, [...(byItem.get(o.item) ?? []), o])
  return attention.filter((a) => resolutionOf(overrideFor(byItem.get(a.item) ?? [], a)) === 'pending')
}

export function pendingAttention(attention: readonly AttentionItem[], overrides: readonly Override[]): { count: number; urgent: boolean } {
  const pending = pendingAttentionItems(attention, overrides)
  return { count: pending.length, urgent: pending.some((a) => a.priority === 'P0') }
}
