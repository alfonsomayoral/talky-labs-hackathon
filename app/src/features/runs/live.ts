// Folds the SSE stream of a backend run (CONTRACT.md §2: one §1.2 event per message, then
// `event: done`) into per-task progress for the live pipeline and the event feed.
import type { AgentEvent, Tasks, TaskKey } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { PIPELINE } from '@/domain/catalog/labels'
import { parseItemId } from '@/engine'

export type NodeState = 'pending' | 'running' | 'done' | 'failed'
export type StreamState = 'connecting' | 'running' | 'done' | 'failed'

export interface TaskProgress {
  state: NodeState
  /** Distinct items with at least one event. */
  items: number
  /** Distinct items with a DECIDE or POST event. */
  decided: number
  /** Progress over `total`: decided items, or accounts touched in bank_rec. */
  done: number
  /** Known size of the task (tasks/), null for ic and close. */
  total: number | null
  fails: number
  lastItem: string | null
}

export interface LiveSnapshot {
  state: StreamState
  tasks: Record<TaskKey, TaskProgress>
  /** Newest first, capped at MAX_FEED. */
  events: AgentEvent[]
  received: number
  error: string | null
}

export const MAX_FEED = 500

export function taskTotals(tasks: Tasks | null | undefined): Partial<Record<TaskKey, number>> {
  if (!tasks) return {}
  return {
    ap: tasks.ap_documents.length,
    ar_billing: tasks.ar_billing_items.length,
    ar_cash: tasks.ar_receipts.length,
    bank_rec: tasks.bank_accounts.length,
  }
}

const isEvent = (x: unknown): x is AgentEvent => typeof x === 'object' && x !== null && typeof (x as AgentEvent).item === 'string'

/** Events of one stream message: a JSON string, an event or a batch. */
function eventsOf(data: unknown): AgentEvent[] {
  let payload = data
  if (typeof payload === 'string') {
    try {
      payload = JSON.parse(payload)
    } catch {
      return []
    }
  }
  return (Array.isArray(payload) ? payload : [payload]).filter(isEvent)
}

/** Shortest time a task is shown running, however fast the backend finished it. */
export const MIN_TASK_MS = 1000
export const PACE_TICK_MS = 100

type StreamMessage = { type: string; data: unknown }

/**
 * Replays the stream at a readable pace. The backend can write a whole task's events in milliseconds and the
 * poll delivers them in one batch; here events keep their order, a task's events are spread over its first
 * `minMs`, the next task starts only after that, and `done` / `error` wait until every event has been shown.
 */
export function createPacer(minMs = MIN_TASK_MS, tickMs = PACE_TICK_MS) {
  const queue: (AgentEvent | StreamMessage)[] = []
  let current: TaskKey | null = null
  let since = 0
  const taskOf = (x: AgentEvent | StreamMessage) => ('item' in x ? (parseItemId(x.item)?.task ?? null) : undefined)

  return {
    push(msg: StreamMessage) {
      if (msg.type !== 'message') queue.push(msg)
      else {
        const events = eventsOf(msg.data)
        // An empty batch still says the run is under way.
        queue.push(...(events.length ? events : [msg]))
      }
    },

    /** Messages to show at `now`; consecutive events are merged into one batch. */
    take(now: number): StreamMessage[] {
      const out: StreamMessage[] = []
      const emit = (x: AgentEvent | StreamMessage) => {
        if (!('item' in x)) return void out.push(x)
        const last = out[out.length - 1]
        if (last?.type === 'message' && Array.isArray(last.data)) last.data.push(x)
        else out.push({ type: 'message', data: [x] })
      }
      while (queue.length) {
        const next = queue[0]
        const task = taskOf(next)
        // Empty batches and events of no task are not paced.
        if (task === null || ('type' in next && next.type === 'message')) {
          emit(queue.shift()!)
          continue
        }
        if (task !== current) {
          if (current !== null && now - since < minMs) break
          if (task === undefined) {
            emit(queue.shift()!)
            continue
          }
          current = task
          since = now
        }
        let run = 0
        while (run < queue.length && taskOf(queue[run]) === current) run++
        const remaining = minMs - (now - since)
        const count = remaining <= 0 ? run : Math.ceil((run * tickMs) / (remaining + tickMs))
        for (let i = 0; i < count; i++) emit(queue.shift()!)
        if (count < run) break
      }
      return out
    },
  }
}

/** Mutable accumulator; `snapshot()` returns an immutable view for React. */
export function createLiveTracker(totals: Partial<Record<TaskKey, number>>) {
  const items = new Map<TaskKey, Set<string>>(TASK_KEYS.map((t) => [t, new Set()]))
  const decided = new Map<TaskKey, Set<string>>(TASK_KEYS.map((t) => [t, new Set()]))
  const accounts = new Set<string>()
  const fails = new Map<TaskKey, number>()
  const last = new Map<TaskKey, string>()
  let feed: AgentEvent[] = []
  let received = 0
  let state: StreamState = 'connecting'
  let error: string | null = null

  function add(e: AgentEvent) {
    const parsed = parseItemId(e.item)
    if (!parsed) return
    const { task, key } = parsed
    received++
    items.get(task)!.add(e.item)
    last.set(task, e.item)
    if (e.kind === 'DECIDE' || e.kind === 'POST') {
      decided.get(task)!.add(e.item)
      if (task === 'bank_rec') accounts.add(key.split('/')[0])
    }
    if (e.result === 'FAIL') fails.set(task, (fails.get(task) ?? 0) + 1)
    feed.unshift(e)
    if (feed.length > MAX_FEED * 2) feed = feed.slice(0, MAX_FEED)
  }

  return {
    /** Feeds one SSE message (`message`, `done` or `error`). */
    push(msg: { type: string; data: unknown }) {
      if (msg.type === 'done') {
        state = 'done'
        return
      }
      if (msg.type === 'error') {
        if (state !== 'done') {
          state = 'failed'
          error = typeof msg.data === 'string' && msg.data ? msg.data : 'Se ha perdido la conexión con el backend'
        }
        return
      }
      let payload: unknown = msg.data
      if (typeof payload === 'string') {
        try {
          payload = JSON.parse(payload)
        } catch {
          return
        }
      }
      for (const e of Array.isArray(payload) ? payload : [payload]) if (isEvent(e)) add(e)
      if (state === 'connecting') state = 'running'
    },

    snapshot(): LiveSnapshot {
      const tasks = {} as Record<TaskKey, TaskProgress>
      for (const t of TASK_KEYS) {
        const total = totals[t] ?? null
        const seen = items.get(t)!.size
        const done = t === 'bank_rec' ? accounts.size : decided.get(t)!.size
        // Tasks run in PIPELINE order: one that has events is finished once a later one has started.
        const overtaken = seen > 0 && PIPELINE.slice(PIPELINE.indexOf(t) + 1).some((later) => items.get(later)!.size > 0)
        const complete = state === 'done' || overtaken || (total !== null && total > 0 && done >= total)
        const nodeState: NodeState = complete ? 'done' : state === 'failed' ? (seen ? 'failed' : 'pending') : seen ? 'running' : 'pending'
        tasks[t] = { state: nodeState, items: seen, decided: decided.get(t)!.size, done, total, fails: fails.get(t) ?? 0, lastItem: last.get(t) ?? null }
      }
      return { state, tasks, events: feed.slice(0, MAX_FEED), received, error }
    },
  }
}

export type LiveTracker = ReturnType<typeof createLiveTracker>
