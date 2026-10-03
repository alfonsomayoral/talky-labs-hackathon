// Conversation history per run (persisted), the answer mode and whether the ⌘J panel is open.

import { create } from 'zustand'
import type { AssistantAnswer, ChatMode } from './engine'

export interface Turn {
  id: string
  question: string
  mode: ChatMode
  askedAt: string
  status: 'pending' | 'done' | 'error'
  answer: AssistantAnswer | null
  error: string | null
}

interface AssistantState {
  byRun: Record<string, Turn[]>
  mode: ChatMode
  panelOpen: boolean
  setMode(mode: ChatMode): void
  setPanelOpen(open: boolean): void
  togglePanel(): void
  addTurn(runId: string, turn: Turn): void
  updateTurn(runId: string, id: string, patch: Partial<Turn>): void
  clear(runId: string): void
}

const KEY = 'kalmora.assistant.v1'
const MAX_TURNS = 50

interface Saved {
  byRun: Record<string, Turn[]>
  mode: ChatMode
}

function load(): Saved {
  try {
    const saved = JSON.parse(localStorage.getItem(KEY) ?? 'null') as Partial<Saved> | null
    return { byRun: saved?.byRun ?? {}, mode: saved?.mode === 'deep' ? 'deep' : 'fast' }
  } catch {
    return { byRun: {}, mode: 'fast' }
  }
}

function save({ byRun, mode }: Saved) {
  // A question still being answered is not kept: after a reload it could never finish.
  const finished = Object.fromEntries(Object.entries(byRun).map(([run, turns]) => [run, turns.filter((t) => t.status !== 'pending')]))
  try {
    localStorage.setItem(KEY, JSON.stringify({ byRun: finished, mode }))
  } catch {
    // Storage unavailable or full: the history lives for this session only.
  }
}

const initial = load()

export const useAssistantStore = create<AssistantState>()((set) => ({
  byRun: initial.byRun,
  mode: initial.mode,
  panelOpen: false,
  setMode: (mode) => set({ mode }),
  setPanelOpen: (panelOpen) => set({ panelOpen }),
  togglePanel: () => set((s) => ({ panelOpen: !s.panelOpen })),
  addTurn: (runId, turn) => set((s) => ({ byRun: { ...s.byRun, [runId]: [...(s.byRun[runId] ?? []), turn].slice(-MAX_TURNS) } })),
  updateTurn: (runId, id, patch) =>
    set((s) => ({ byRun: { ...s.byRun, [runId]: (s.byRun[runId] ?? []).map((t) => (t.id === id ? { ...t, ...patch } : t)) } })),
  clear: (runId) =>
    set((s) => {
      const byRun = { ...s.byRun }
      delete byRun[runId]
      return { byRun }
    }),
}))

useAssistantStore.subscribe((s, prev) => {
  if (s.byRun !== prev.byRun || s.mode !== prev.mode) save(s)
})

/** Opens the assistant side panel (⌘J) from anywhere. */
export const openAssistantPanel = () => useAssistantStore.getState().setPanelOpen(true)
