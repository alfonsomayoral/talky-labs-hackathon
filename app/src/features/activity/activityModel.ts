// Actividad: filters in the URL (shareable links) and the pure filtering of items and events.

import type { AgentEvent, ItemId, TaskKey, WorkItem } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { outcomeEntry } from '@/domain/catalog/policy'

export type ActivityView = 'items' | 'timeline'
export type AttentionFilter = 'yes' | 'no' | null

export interface ActivityFilters {
  task: TaskKey | null
  view: ActivityView
  status: string[]
  company: string[]
  /** `<task>:<outcome>` so codes shared by two tasks stay apart. */
  outcome: string[]
  attention: AttentionFilter
  q: string
  /** Selected ProcessMap node or breakdown entry (FlowFilter id). */
  node: string | null
  group: string | null
  /** Timeline: event kinds and results. */
  kind: string[]
  result: string[]
}

// URL parameter names (Spanish: they show in shared links).
const P = {
  task: 'tarea',
  view: 'vista',
  status: 'estado',
  company: 'sociedad',
  outcome: 'resultado',
  attention: 'atencion',
  q: 'q',
  node: 'nodo',
  group: 'agrupar',
  kind: 'paso',
  result: 'res',
} as const

const list = (v: string | null): string[] => (v ? v.split(',').filter(Boolean) : [])

export function parseActivityParams(params: URLSearchParams): ActivityFilters {
  const task = params.get(P.task)
  const attention = params.get(P.attention)
  return {
    task: TASK_KEYS.includes(task as TaskKey) ? (task as TaskKey) : null,
    view: params.get(P.view) === 'linea' ? 'timeline' : 'items',
    status: list(params.get(P.status)),
    company: list(params.get(P.company)),
    outcome: list(params.get(P.outcome)),
    attention: attention === 'si' ? 'yes' : attention === 'no' ? 'no' : null,
    q: params.get(P.q) ?? '',
    node: params.get(P.node),
    group: params.get(P.group),
    kind: list(params.get(P.kind)),
    result: list(params.get(P.result)),
  }
}

/** Applies a patch to the current params, keeping the ones Actividad does not own (e.g. `item`). */
export function applyActivityParams(prev: URLSearchParams, patch: Partial<ActivityFilters>): URLSearchParams {
  const next = new URLSearchParams(prev)
  const set = (name: string, value: string | null) => (value ? next.set(name, value) : next.delete(name))
  for (const [k, v] of Object.entries(patch) as [keyof ActivityFilters, unknown][]) {
    const name = P[k]
    if (k === 'view') set(name, v === 'timeline' ? 'linea' : null)
    else if (k === 'attention') set(name, v === 'yes' ? 'si' : v === 'no' ? 'no' : null)
    else if (Array.isArray(v)) set(name, v.length ? v.join(',') : null)
    else set(name, typeof v === 'string' && v ? v : null)
  }
  return next
}

/** Clears every filter but the task and the view. */
export const CLEARED: Partial<ActivityFilters> = { status: [], company: [], outcome: [], attention: null, q: '', node: null, kind: [], result: [] }

export const outcomeKey = (it: Pick<WorkItem, 'task' | 'outcome'>) => `${it.task}:${it.outcome}`

export function outcomeLabel(key: string, withTask: boolean, taskLabel: (t: TaskKey) => string): string {
  const i = key.indexOf(':')
  const task = key.slice(0, i) as TaskKey
  const outcome = key.slice(i + 1)
  const label = (TASK_KEYS.includes(task) && outcomeEntry(task, outcome)?.label) || (outcome === 'MATCH' ? 'Casado' : outcome)
  return withTask && TASK_KEYS.includes(task) ? `${taskLabel(task)} · ${label}` : label
}

const normalize = (s: string) =>
  s
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()

export interface ItemFilterContext {
  attention: ReadonlySet<ItemId>
  /** Items of the selected ProcessMap node, or null. */
  node: ReadonlySet<ItemId> | null
}

export function filterItems(items: readonly WorkItem[], f: ActivityFilters, ctx: ItemFilterContext): WorkItem[] {
  const q = normalize(f.q.trim())
  const status = new Set(f.status)
  const company = new Set(f.company)
  const outcome = new Set(f.outcome)
  return items.filter((it) => {
    if (f.task && it.task !== f.task) return false
    if (ctx.node && !ctx.node.has(it.id)) return false
    if (status.size && !status.has(it.status)) return false
    if (company.size && !company.has(it.company ?? '—')) return false
    if (outcome.size && !outcome.has(outcomeKey(it))) return false
    if (f.attention === 'yes' && !ctx.attention.has(it.id)) return false
    if (f.attention === 'no' && ctx.attention.has(it.id)) return false
    if (q) {
      const hay = normalize([it.id, it.title, it.counterparty ?? '', it.outcome, it.company ?? '', ...it.reasons].join(' '))
      if (!q.split(/\s+/).every((t) => hay.includes(t))) return false
    }
    return true
  })
}

/** Events of the timeline: by task, kind, result and text; chronological (ts, then item order, then seq). */
export function filterEvents(events: readonly AgentEvent[], f: ActivityFilters, taskOf: (item: string) => TaskKey | null): AgentEvent[] {
  const q = normalize(f.q.trim())
  const kind = new Set(f.kind)
  const result = new Set(f.result)
  const out = events.filter((e) => {
    if (f.task && taskOf(e.item) !== f.task) return false
    if (kind.size && !kind.has(e.kind)) return false
    if (result.size && !result.has(e.result)) return false
    if (q && !normalize(`${e.item} ${e.summary} ${e.step} ${e.policy_ref ?? ''}`).includes(q)) return false
    return true
  })
  const order = new Map<AgentEvent, number>()
  events.forEach((e, i) => order.set(e, i))
  return out.sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : order.get(a)! - order.get(b)!))
}

/** Counts per value of a key (for FilterChip options). */
export function countBy<T>(rows: readonly T[], key: (r: T) => string): Map<string, number> {
  const m = new Map<string, number>()
  for (const r of rows) {
    const k = key(r)
    m.set(k, (m.get(k) ?? 0) + 1)
  }
  return m
}
