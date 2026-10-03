// Counters for the overview: items by status and task, attention load, unbalanced entries.

import type { AttentionItem, RunStats, TaskKey, ValidationReport, WorkItem } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import type { ToEur } from '../fx'

export function computeStats(items: readonly WorkItem[], attention: readonly AttentionItem[], validation: ValidationReport, toEur?: ToEur): RunStats {
  const companyOf = new Map(items.map((it) => [it.id, it.company]))
  const byStatus: Record<string, number> = {}
  const byTask = Object.fromEntries(TASK_KEYS.map((k) => [k, { items: 0, auto: 0, needsHuman: 0, blocked: 0, open: 0 }])) as RunStats['byTask']
  for (const it of items) {
    byStatus[it.status] = (byStatus[it.status] ?? 0) + 1
    const t = byTask[it.task as TaskKey]
    t.items++
    if (it.status === 'AUTO') t.auto++
    else if (it.status === 'NEEDS_HUMAN') t.needsHuman++
    else if (it.status === 'BLOCKED') t.blocked++
    else t.open++
  }
  const byPriority: Record<string, number> = {}
  let impact = 0
  let impactEur = 0
  for (const a of attention) {
    byPriority[a.priority] = (byPriority[a.priority] ?? 0) + 1
    impact += a.impact
    impactEur += toEur ? toEur(companyOf.get(a.item), a.impact) : a.impact
  }
  return {
    items: items.length,
    byStatus,
    byTask,
    attention: { count: attention.length, impact, impactEur, byPriority },
    unbalancedEntries: TASK_KEYS.reduce((s, k) => s + validation.files[k].unbalancedEntries.length, 0),
  }
}
