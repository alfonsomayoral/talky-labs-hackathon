// Public store API of the data layer (frozen contract — phase 1.B implements it).
// Views and the engine glue import ONLY from this module, never from data internals.

import { create } from 'zustand'
import type { DatasetApi, DatasetMeta, RunBundle } from '@/domain/types'

export type LoadStatus = 'idle' | 'loading' | 'ready' | 'error'

export interface LoadProgress {
  phase: string
  done: number
  total: number
}

export interface DatasetState {
  /** Known datasets (persisted metadata), newest first. */
  datasets: DatasetMeta[]
  activeId: string | null
  /** API of the active dataset once loaded. */
  api: DatasetApi | null
  status: LoadStatus
  progress: LoadProgress | null
  error: string | null
  /** Datasets served by the dev middleware or the backend (`/__data`, `GET /api/datasets`). */
  available: { id: string; name: string; source: 'dev' | 'api' }[]
  refreshAvailable(): Promise<void>
  /** Files from a dropped/picked folder (with `webkitRelativePath`) or a FileSystemDirectoryHandle. */
  loadFromFolder(input: File[] | FileSystemDirectoryHandle): Promise<DatasetMeta>
  loadFromZip(file: File): Promise<DatasetMeta>
  loadFromHttp(id: string): Promise<DatasetMeta>
  /** Re-open a persisted dataset by id. */
  activate(id: string): Promise<void>
  remove(id: string): Promise<void>
}

export interface RunState {
  runs: RunBundle[]
  activeId: string | null
  status: LoadStatus
  error: string | null
  /** Builds a run from the active dataset's golden/ (dev only). */
  createGoldenRun(): Promise<RunBundle>
  /** Imports the 6 JSONL (loose files), a bundle folder (deliverables/, trace/, manifest.json) or a zip of either. */
  importRun(input: File[] | File | FileSystemDirectoryHandle, label?: string): Promise<RunBundle>
  /** Bundles served by the dev middleware (`/__runs`) or the backend API. */
  listRemoteRuns(): Promise<{ id: string; label: string; source: 'dev' | 'api' }[]>
  loadRemoteRun(id: string): Promise<RunBundle>
  /** Starts a close on the backend (requires VITE_API_URL); resolves with the run id. Events stream via subscribeRun. */
  startApiRun(datasetId: string): Promise<string>
  subscribeRun(runId: string, onEvent: (e: MessageEvent) => void): () => void
  setActive(id: string | null): void
  remove(id: string): Promise<void>
}

const notImplemented = (what: string) => () => Promise.reject(new Error(`${what}: not implemented yet`))

export const useDatasetStore = create<DatasetState>(() => ({
  datasets: [],
  activeId: null,
  api: null,
  status: 'idle',
  progress: null,
  error: null,
  available: [],
  refreshAvailable: notImplemented('refreshAvailable'),
  loadFromFolder: notImplemented('loadFromFolder'),
  loadFromZip: notImplemented('loadFromZip'),
  loadFromHttp: notImplemented('loadFromHttp'),
  activate: notImplemented('activate'),
  remove: notImplemented('remove'),
}))

export const useRunStore = create<RunState>(() => ({
  runs: [],
  activeId: null,
  status: 'idle',
  error: null,
  createGoldenRun: notImplemented('createGoldenRun'),
  importRun: notImplemented('importRun'),
  listRemoteRuns: notImplemented('listRemoteRuns'),
  loadRemoteRun: notImplemented('loadRemoteRun'),
  startApiRun: notImplemented('startApiRun'),
  subscribeRun: () => () => {},
  setActive: () => {},
  remove: notImplemented('remove'),
}))
