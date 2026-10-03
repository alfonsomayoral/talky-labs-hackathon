// IndexedDB persistence (idb-keyval): dataset metadata + how to reopen each one (its origin),
// runs per dataset and the active session. Best effort: failures never block a load.
import { createStore, del, get, set, type UseStore } from 'idb-keyval'
import type { DatasetMeta, RunBundle } from '@/domain/types'
import type { DatasetOrigin } from './providers/types'

export interface Session {
  datasetId: string | null
  /** Active run per dataset. */
  runs: Record<string, string | null>
}

let db: UseStore | null = null
const store = () => (db ??= createStore('kalmora-close', 'kv'))
export const persistenceAvailable = () => typeof indexedDB !== 'undefined'

async function safe<T>(fn: () => Promise<T>, fallback: T): Promise<T> {
  if (!persistenceAvailable()) return fallback
  try {
    return await fn()
  } catch (e) {
    console.warn('[kalmora] IndexedDB:', e)
    return fallback
  }
}

export const loadDatasets = () => safe(async () => (await get<DatasetMeta[]>('datasets', store())) ?? [], [] as DatasetMeta[])
export const saveDatasets = (list: DatasetMeta[]) => safe(() => set('datasets', list, store()), undefined)

export const loadOrigin = (id: string) =>
  safe(async () => {
    const origin = await get<DatasetOrigin>(`origin:${id}`, store())
    return origin && 'provider' in origin ? origin : null
  }, null)
export const saveOrigin = (id: string, origin: DatasetOrigin) => safe(() => set(`origin:${id}`, origin, store()), undefined)

export const loadRuns = (datasetId: string) => safe(async () => (await get<RunBundle[]>(`runs:${datasetId}`, store())) ?? [], [] as RunBundle[])
export const saveRuns = (datasetId: string, runs: RunBundle[]) => safe(() => set(`runs:${datasetId}`, runs, store()), undefined)

export const loadSession = () => safe(async () => (await get<Session>('session', store())) ?? { datasetId: null, runs: {} }, { datasetId: null, runs: {} } as Session)
export const saveSession = (s: Session) => safe(() => set('session', s, store()), undefined)

export const forgetDataset = (id: string) =>
  safe(async () => {
    await del(`origin:${id}`, store())
    await del(`runs:${id}`, store())
  }, undefined)
