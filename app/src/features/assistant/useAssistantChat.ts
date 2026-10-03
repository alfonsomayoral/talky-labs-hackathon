// Glue between the stores, the active run and the answer engine. Shared by the page and the ⌘J panel.

import { useCallback } from 'react'
import { useDatasetStore } from '@/data/stores'
import { useActiveRun, useDerivedRun } from '@/engine'
import { useOverridesStore, type Override } from '@/features/attention/overridesStore'
import { askAssistant, type ChatMessage } from './engine'
import { useAssistantStore, type Turn } from './store'

const NO_TURNS: Turn[] = []
const NO_OVERRIDES: Override[] = []

const newId = () => `t-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`
const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

export function useAssistantChat() {
  const { data, status, error } = useDerivedRun()
  const run = useActiveRun()
  const api = useDatasetStore((s) => s.api)
  const runId = run?.id ?? null
  const overrides = useOverridesStore((s) => (runId ? s.byRun[runId] : undefined)) ?? NO_OVERRIDES
  const turns = useAssistantStore((s) => (runId ? s.byRun[runId] : undefined)) ?? NO_TURNS
  const mode = useAssistantStore((s) => s.mode)
  const setMode = useAssistantStore((s) => s.setMode)
  const ready = status === 'ready' && !!data && !!run && !!api

  const ask = useCallback(
    async (question: string) => {
      const q = question.trim()
      if (!q || !data || !run || !api) return
      const store = useAssistantStore.getState()
      const history: ChatMessage[] = (store.byRun[run.id] ?? [])
        .filter((t) => t.status === 'done' && t.answer)
        .flatMap((t) => [
          { role: 'user' as const, content: t.question },
          { role: 'assistant' as const, content: t.answer!.text },
        ])
      const id = newId()
      store.addTurn(run.id, { id, question: q, mode, askedAt: new Date().toISOString(), status: 'pending', answer: null, error: null })
      const ctx = { data, core: api.core, meta: api.meta, run, overrides, mode }
      try {
        const answer = await askAssistant(q, ctx, { history, onUpdate: (partial) => store.updateTurn(run.id, id, { answer: partial }) })
        store.updateTurn(run.id, id, { status: 'done', answer })
      } catch (e) {
        store.updateTurn(run.id, id, { status: 'error', error: message(e) })
      }
    },
    [data, run, api, overrides, mode],
  )

  const clear = useCallback(() => {
    if (runId) useAssistantStore.getState().clear(runId)
  }, [runId])

  return { ready, status, error, turns, ask, clear, mode, setMode, busy: turns.some((t) => t.status === 'pending') }
}
