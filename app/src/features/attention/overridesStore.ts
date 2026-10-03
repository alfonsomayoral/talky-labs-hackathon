// Human decisions taken in the Attention queue (frozen contract — phase 2.D extends it).
// They never modify the delivered JSONL: they are exported apart as overrides.jsonl (CONTRACT.md §3).

import { create } from 'zustand'

export type OverrideAction = 'ACCEPT' | 'CHOOSE_ALTERNATIVE' | 'SNOOZE' | 'NOTE'

export interface Override {
  runId: string
  attention_id: string | null
  item: string
  action: OverrideAction
  /** Decision chosen when the action is CHOOSE_ALTERNATIVE (or the accepted one). */
  decision: string | null
  note: string | null
  user: string
  ts: string
}

interface OverridesState {
  byRun: Record<string, Override[]>
  add(o: Omit<Override, 'ts' | 'user'> & { user?: string }): void
  remove(runId: string, item: string): void
  forRun(runId: string): Override[]
  /** One JSON object per line, CONTRACT.md §3 shape. */
  toJsonl(runId: string): string
}

const KEY = 'kalmora.overrides.v1'

const load = (): Record<string, Override[]> => {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? '{}') as Record<string, Override[]>
  } catch {
    return {}
  }
}

const save = (byRun: Record<string, Override[]>) => {
  try {
    localStorage.setItem(KEY, JSON.stringify(byRun))
  } catch {
    // Storage may be unavailable (private mode); overrides then live for the session only.
  }
}

export const useOverridesStore = create<OverridesState>()((set, get) => ({
  byRun: load(),
  add(o) {
    const entry: Override = { ...o, user: o.user ?? 'revisor', ts: new Date().toISOString() }
    const list = (get().byRun[o.runId] ?? []).filter((x) => x.item !== o.item)
    const byRun = { ...get().byRun, [o.runId]: [...list, entry] }
    save(byRun)
    set({ byRun })
  },
  remove(runId, item) {
    const byRun = { ...get().byRun, [runId]: (get().byRun[runId] ?? []).filter((x) => x.item !== item) }
    save(byRun)
    set({ byRun })
  },
  forRun(runId) {
    return get().byRun[runId] ?? []
  },
  toJsonl(runId) {
    return get()
      .forRun(runId)
      .map((o) => JSON.stringify({ attention_id: o.attention_id, item: o.item, action: o.action, decision: o.decision, note: o.note, user: o.user, ts: o.ts }))
      .join('\n')
  },
}))
