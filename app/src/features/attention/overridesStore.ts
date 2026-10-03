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

export type NewOverride = Omit<Override, 'ts' | 'user' | 'note'> & {
  user?: string
  /** Omitted keeps the note already saved for the same target. */
  note?: string | null
}

interface OverridesState {
  byRun: Record<string, Override[]>
  /** Adds or replaces the override of the same (item, attention_id). */
  add(o: NewOverride): void
  /** Removes the overrides of an item; with `attentionId`, only the one of that attention entry. */
  remove(runId: string, item: string, attentionId?: string | null): void
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

const sameTarget = (x: Override, item: string, attentionId: string | null) => x.item === item && x.attention_id === attentionId

export const useOverridesStore = create<OverridesState>()((set, get) => ({
  byRun: load(),
  add(o) {
    const current = get().byRun[o.runId] ?? []
    const previous = current.find((x) => sameTarget(x, o.item, o.attention_id))
    const entry: Override = { ...o, note: o.note === undefined ? (previous?.note ?? null) : o.note, user: o.user ?? 'revisor', ts: new Date().toISOString() }
    const byRun = { ...get().byRun, [o.runId]: [...current.filter((x) => x !== previous), entry] }
    save(byRun)
    set({ byRun })
  },
  remove(runId, item, attentionId) {
    const keep = (x: Override) => (attentionId === undefined ? x.item !== item : !sameTarget(x, item, attentionId))
    const byRun = { ...get().byRun, [runId]: (get().byRun[runId] ?? []).filter(keep) }
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
