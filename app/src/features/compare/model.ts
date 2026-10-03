// Comparar con golden: rows of the per-item comparison, task sub-scores and the URL state.

import type { ItemId, ItemScore, ScoreReport, TaskKey } from '@/domain/types'
import { TASK_KEYS, TASK_WEIGHTS } from '@/domain/types'
import { PIPELINE } from '@/domain/catalog/labels'

export type CompareView = 'diff' | 'all'

export interface CompareParams {
  view: CompareView
  task: TaskKey | null
}

// URL parameter names (Spanish: they show in shared links).
const P = { view: 'vista', task: 'tarea' } as const

export function parseCompareParams(params: URLSearchParams): CompareParams {
  const task = params.get(P.task)
  return {
    view: params.get(P.view) === 'todo' ? 'all' : 'diff',
    task: TASK_KEYS.includes(task as TaskKey) ? (task as TaskKey) : null,
  }
}

/** Applies a patch, keeping the params Comparar does not own (e.g. `item`). */
export function applyCompareParams(prev: URLSearchParams, patch: Partial<CompareParams>): URLSearchParams {
  const next = new URLSearchParams(prev)
  if ('view' in patch) {
    if (patch.view === 'all') next.set(P.view, 'todo')
    else next.delete(P.view)
  }
  if ('task' in patch) {
    if (patch.task) next.set(P.task, patch.task)
    else next.delete(P.task)
  }
  return next
}

/** missing: in golden, not delivered · extra: delivered, not in golden · different: both, with differences. */
/** `inherited`: no differences of its own but less than full credit (a bank account loses it through its match items). */
export type DiffKind = 'missing' | 'extra' | 'different' | 'exact' | 'inherited'

export interface DiffRow {
  id: ItemId
  task: TaskKey
  key: string
  kind: DiffKind
  /** 0..1 credit of the item as the scorer sees it (null for items golden does not have). */
  score: number | null
  diffs: number
  /** Distinct diff paths, in order. */
  paths: string[]
  /** Approximate points of the total (0–100) the item loses; null when its score is unknown. */
  loss: number | null
}

function kindOf(s: ItemScore): DiffKind {
  const only = s.diffs.length === 1 && s.diffs[0].path === 'item' ? s.diffs[0] : null
  if (only?.actual === null) return 'missing'
  if (only?.expected === null) return 'extra'
  if (!s.exact) return 'different'
  return s.score !== null && s.score < 1 - 1e-9 ? 'inherited' : 'exact'
}

function split(id: ItemId): { task: TaskKey; key: string } {
  const i = id.indexOf(':')
  return { task: id.slice(0, i) as TaskKey, key: id.slice(i + 1) }
}

// Bank items come at two levels (account and line); each level is weighed against its own count.
const level = (task: TaskKey, key: string) => (task === 'bank_rec' && !key.includes('/') ? 'bank_rec#account' : task)

/**
 * Rows of the per-item comparison, ordered by points lost (unknown last, then by number of
 * differences). The loss is weight × (1 − item score) ÷ golden items of the task: exact for
 * averaged tasks, an estimate for F1-scored ones.
 */
export function diffRows(perItem: Record<ItemId, ItemScore>, opts: { all?: boolean; task?: TaskKey | null } = {}): DiffRow[] {
  const scores = Object.values(perItem)
  const goldCount = new Map<string, number>()
  const base = scores.map((s) => {
    const { task, key } = split(s.item)
    const kind = kindOf(s)
    if (kind !== 'extra') goldCount.set(level(task, key), (goldCount.get(level(task, key)) ?? 0) + 1)
    return { s, task, key, kind }
  })
  const rows: DiffRow[] = []
  for (const { s, task, key, kind } of base) {
    if (!opts.all && s.exact) continue
    if (opts.task && task !== opts.task) continue
    const n = goldCount.get(level(task, key)) ?? 0
    rows.push({
      id: s.item,
      task,
      key,
      kind,
      score: s.score,
      diffs: s.diffs.length,
      paths: [...new Set(s.diffs.map((d) => d.path))],
      loss: s.score === null || kind === 'extra' || n === 0 ? null : (TASK_WEIGHTS[task] * (1 - s.score) * 100) / n,
    })
  }
  return rows.sort((a, b) => (b.loss ?? -1) - (a.loss ?? -1) || b.diffs - a.diffs || a.id.localeCompare(b.id))
}

export type ScoreRow = TaskKey | 'trial_balance'

export interface TaskSummary {
  task: ScoreRow
  weight: number
  score: number
  /** Points of the total (0–100) the task contributes: weight × score × 100. */
  contributes: number
  /** Points of the total it loses: weight × (1 − score) × 100. */
  lost: number
  /** Items that differ from golden (null for the trial balance, scored as a whole). */
  differing: number | null
}

/** Sub-scores in pipeline order, then the trial balance. */
export function taskSummaries(score: ScoreReport): TaskSummary[] {
  const differing = new Map<TaskKey, number>()
  for (const s of Object.values(score.perItem)) {
    if (s.exact) continue
    const { task } = split(s.item)
    differing.set(task, (differing.get(task) ?? 0) + 1)
  }
  return [...PIPELINE, 'trial_balance' as const].map((task) => {
    const weight = TASK_WEIGHTS[task]
    const value = score.tasks[task].score
    return {
      task,
      weight,
      score: value,
      contributes: weight * value * 100,
      lost: weight * (1 - value) * 100,
      differing: task === 'trial_balance' ? null : (differing.get(task) ?? 0),
    }
  })
}
