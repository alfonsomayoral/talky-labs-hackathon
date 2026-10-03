// Glue between the data stores and the engine.
// Frozen contract: views call this hook to get everything derived for the active dataset + run.
import { useCallback, useMemo, useSyncExternalStore } from 'react'
import { useDatasetStore, useRunStore } from '@/data/stores'
import type { AgentEvent, AttentionItem, DatasetApi, DatasetCore, DerivedRun, ItemId, RunBundle, TrialBalanceRow, WorkItem } from '@/domain/types'
import { deriveRun, withTrialBalance } from './derive/deriveRun'

export interface DerivedRunState {
  data: DerivedRun | null
  status: 'idle' | 'loading' | 'ready' | 'error'
  error: string | null
}

const message = (e: unknown): string => (e instanceof Error ? e.message : String(e))

// ---------------------------------------------------------------- recorded trial balance (once per dataset)
interface TbState {
  rows: TrialBalanceRow[] | null
  error: string | null
  started: boolean
  listeners: Set<() => void>
}

const tbByApi = new WeakMap<DatasetApi, TbState>()

function subscribeTb(api: DatasetApi, onChange: () => void): () => void {
  let s = tbByApi.get(api)
  if (!s) tbByApi.set(api, (s = { rows: null, error: null, started: false, listeners: new Set() }))
  const state = s
  state.listeners.add(onChange)
  if (!state.started) {
    state.started = true
    const notify = () => state.listeners.forEach((l) => l())
    api.recordedTrialBalance().then(
      (rows) => {
        state.rows = rows
        notify()
      },
      (e: unknown) => {
        state.error = message(e)
        notify()
      },
    )
  }
  return () => state.listeners.delete(onChange)
}

function useRecordedTrialBalance(api: DatasetApi | null): TrialBalanceRow[] | null {
  const subscribe = useCallback((cb: () => void) => (api ? subscribeTb(api, cb) : () => {}), [api])
  return useSyncExternalStore(subscribe, () => (api ? (tbByApi.get(api)?.rows ?? null) : null))
}

// ---------------------------------------------------------------- derived run cache per (dataset id, run id)
interface CacheEntry {
  core: DatasetCore
  run: RunBundle
  base: DerivedRun
  withTb: { recorded: TrialBalanceRow[]; data: DerivedRun } | null
}

const MAX_CACHED = 8
const cache = new Map<string, CacheEntry>()

function derived(api: DatasetApi, run: RunBundle, recorded: TrialBalanceRow[] | null): DerivedRun {
  const key = `${api.meta.id}|${run.id}`
  let entry = cache.get(key)
  if (!entry || entry.core !== api.core || entry.run !== run) {
    entry = { core: api.core, run, base: deriveRun(api.core, run, null), withTb: null }
    cache.delete(key)
    cache.set(key, entry)
    if (cache.size > MAX_CACHED) cache.delete(cache.keys().next().value as string)
  }
  if (!recorded) return entry.base
  if (entry.withTb?.recorded !== recorded) entry.withTb = { recorded, data: withTrialBalance(entry.base, api.core, run, recorded) }
  return entry.withTb.data
}

/** Everything derived for the active dataset + run; the trial balance fills in when the journal has been summed. */
export function useDerivedRun(): DerivedRunState {
  const api = useDatasetStore((s) => s.api)
  const datasetStatus = useDatasetStore((s) => s.status)
  const datasetError = useDatasetStore((s) => s.error)
  const run = useRunStore((s) => s.runs.find((r) => r.id === s.activeId) ?? null)
  const runStatus = useRunStore((s) => s.status)
  const runError = useRunStore((s) => s.error)
  const recorded = useRecordedTrialBalance(api)

  return useMemo((): DerivedRunState => {
    if (!api) {
      if (datasetStatus === 'loading') return { data: null, status: 'loading', error: null }
      return datasetStatus === 'error' ? { data: null, status: 'error', error: datasetError } : IDLE
    }
    if (!run) {
      if (runStatus === 'loading') return { data: null, status: 'loading', error: null }
      return runStatus === 'error' ? { data: null, status: 'error', error: runError } : IDLE
    }
    try {
      return { data: derived(api, run, recorded), status: 'ready', error: null }
    } catch (e) {
      return { data: null, status: 'error', error: message(e) }
    }
  }, [api, run, recorded, datasetStatus, datasetError, runStatus, runError])
}

const IDLE: DerivedRunState = { data: null, status: 'idle', error: null }
const NO_EVENTS: AgentEvent[] = []
const NO_ATTENTION: AttentionItem[] = []

// ---------------------------------------------------------------- selectors
export function useActiveRun(): RunBundle | null {
  return useRunStore((s) => s.runs.find((r) => r.id === s.activeId) ?? null)
}

export function useItem(itemId: ItemId | null | undefined): WorkItem | null {
  const { data } = useDerivedRun()
  return (itemId && data?.itemsById.get(itemId)) || null
}

export function useItemEvents(itemId: ItemId | null | undefined): AgentEvent[] {
  const { data } = useDerivedRun()
  return (itemId && data?.eventsByItem.get(itemId)) || NO_EVENTS
}

export function useAttention(): AttentionItem[] {
  return useDerivedRun().data?.attention ?? NO_ATTENTION
}
