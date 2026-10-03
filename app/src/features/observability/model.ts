// Pure figures behind /coste: model usage from the manifest, task timing and confidence calibration.

import type { AgentEvent, ItemId, ItemScore, ModelUsage, RunManifest, TaskKey, WorkItem } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { parseItemId } from '@/engine'

// ---------------------------------------------------------------- cost

export interface CostSummary {
  models: ModelUsage[]
  calls: number
  inputTokens: number
  outputTokens: number
  /** Null when the manifest says nothing about cost. */
  costUsd: number | null
  runtimeMs: number | null
}

const time = (iso: string | undefined): number | null => {
  if (!iso) return null
  const t = Date.parse(iso)
  return Number.isNaN(t) ? null : t
}

export function costSummary(manifest: RunManifest | null): CostSummary {
  const models = [...(manifest?.models ?? [])].sort((a, b) => b.cost_usd - a.cost_usd || b.calls - a.calls)
  const sum = (f: (m: ModelUsage) => number) => models.reduce((s, m) => s + (f(m) || 0), 0)
  const start = time(manifest?.started_at)
  const end = time(manifest?.finished_at)
  return {
    models,
    calls: sum((m) => m.calls),
    inputTokens: sum((m) => m.input_tokens),
    outputTokens: sum((m) => m.output_tokens),
    costUsd: manifest?.cost_usd_total ?? (models.length ? sum((m) => m.cost_usd) : null),
    runtimeMs: manifest?.runtime_s != null ? manifest.runtime_s * 1000 : start !== null && end !== null ? end - start : null,
  }
}

// ---------------------------------------------------------------- timeline

export interface TaskSpan {
  task: TaskKey
  /** Milliseconds from the start of the run. */
  start: number
  end: number
}

export interface Timeline {
  source: 'manifest' | 'events'
  /** Epoch ms of the run start. */
  origin: number
  total: number
  spans: TaskSpan[]
}

function fromSpans(source: Timeline['source'], raw: { task: TaskKey; start: number; end: number }[], runStart: number | null): Timeline | null {
  if (!raw.length) return null
  const origin = Math.min(runStart ?? Infinity, ...raw.map((s) => s.start))
  const spans = raw.map((s) => ({ task: s.task, start: s.start - origin, end: s.end - origin }))
  const total = Math.max(...spans.map((s) => s.end))
  return total > 0 ? { source, origin, total, spans } : null
}

/**
 * Duration per task: `manifest.tasks` when it has both ends, otherwise the span of each task's
 * backend events (ts + duration_ms). Null when neither carries timing (e.g. a synthesized trace).
 */
export function taskTimeline(manifest: RunManifest | null, events: AgentEvent[] | null): Timeline | null {
  const runStart = time(manifest?.started_at)
  const fromManifest: TaskSpan[] = []
  for (const task of TASK_KEYS) {
    const t = manifest?.tasks?.[task]
    const start = time(t?.started_at)
    const end = time(t?.finished_at)
    if (start !== null && end !== null && end >= start) fromManifest.push({ task, start, end })
  }
  if (fromManifest.length) return fromSpans('manifest', fromManifest, runStart)

  const byTask = new Map<TaskKey, { start: number; end: number }>()
  for (const e of events ?? []) {
    const task = parseItemId(e.item)?.task
    const ts = time(e.ts)
    if (!task || ts === null) continue
    const end = ts + (e.duration_ms ?? 0)
    const span = byTask.get(task)
    if (!span) byTask.set(task, { start: ts, end })
    else {
      span.start = Math.min(span.start, ts)
      span.end = Math.max(span.end, end)
    }
  }
  const fromEvents = TASK_KEYS.filter((t) => byTask.has(t)).map((task) => ({ task, ...byTask.get(task)! }))
  return fromSpans('events', fromEvents, runStart)
}

// ---------------------------------------------------------------- calibration

export interface ConfidencePoint {
  item: ItemId
  task: TaskKey
  /** Probability that the item's final decision is right (DECIDE event). */
  p: number
  /** Matches golden exactly; null without golden. */
  correct: boolean | null
}

export function confidencePoints(items: WorkItem[], perItem: Record<ItemId, ItemScore> | null): ConfidencePoint[] {
  const out: ConfidencePoint[] = []
  for (const it of items) {
    if (it.confidence == null || !Number.isFinite(it.confidence)) continue
    const p = Math.min(1, Math.max(0, it.confidence))
    out.push({ item: it.id, task: it.task, p, correct: perItem ? (perItem[it.id]?.exact ?? null) : null })
  }
  return out
}

export interface ReliabilityBin {
  lo: number
  hi: number
  count: number
  /** Points whose correctness is known (golden). */
  known: number
  meanP: number | null
  accuracy: number | null
}

/** Equal-width bins over [0, 1]; p = 1 falls in the last bin. */
export function reliabilityBins(points: ConfidencePoint[], bins = 10): ReliabilityBin[] {
  const out: ReliabilityBin[] = Array.from({ length: bins }, (_, i) => ({ lo: i / bins, hi: (i + 1) / bins, count: 0, known: 0, meanP: null, accuracy: null }))
  const sums = out.map(() => ({ p: 0, pKnown: 0, right: 0 }))
  for (const pt of points) {
    const i = Math.min(bins - 1, Math.floor(pt.p * bins))
    out[i].count++
    sums[i].p += pt.p
    if (pt.correct !== null) {
      out[i].known++
      sums[i].pKnown += pt.p
      if (pt.correct) sums[i].right++
    }
  }
  out.forEach((b, i) => {
    if (b.known) {
      b.meanP = sums[i].pKnown / b.known
      b.accuracy = sums[i].right / b.known
    } else if (b.count) b.meanP = sums[i].p / b.count
  })
  return out
}

/** Expected calibration error: Σ (known_b / known) · |accuracy_b − meanP_b|. Null without known points. */
export function expectedCalibrationError(bins: ReliabilityBin[]): number | null {
  const known = bins.reduce((s, b) => s + b.known, 0)
  if (!known) return null
  return bins.reduce((s, b) => (b.known ? s + (b.known / known) * Math.abs((b.accuracy ?? 0) - (b.meanP ?? 0)) : s), 0)
}

export interface ThresholdStats {
  threshold: number
  total: number
  /** Items at or above the threshold: the agent would close them alone. */
  auto: number
  toHuman: number
  coverage: number
  /** Σ (1 − p) over the auto items: errors the model itself expects to let through. */
  expectedErrors: number
  /** Wrong auto items according to golden; null without golden. */
  actualErrors: number | null
  /** Share of right auto items among those with known correctness. */
  accuracy: number | null
}

export function thresholdStats(points: ConfidencePoint[], threshold: number): ThresholdStats {
  let auto = 0
  let expectedErrors = 0
  let known = 0
  let wrong = 0
  for (const pt of points) {
    if (pt.p < threshold) continue
    auto++
    expectedErrors += 1 - pt.p
    if (pt.correct !== null) {
      known++
      if (!pt.correct) wrong++
    }
  }
  const total = points.length
  return {
    threshold,
    total,
    auto,
    toHuman: total - auto,
    coverage: total ? auto / total : 0,
    expectedErrors,
    actualErrors: known ? wrong : null,
    accuracy: known ? (known - wrong) / known : null,
  }
}
