// Provider boundary: where datasets and run bundles come from. Stores only talk to providers;
// switching to the backend's API means changing a provider, never the stores or the views.
import type { DatasetApi, DatasetMeta, RunBundle } from '@/domain/types'
import type { SourceDescriptor } from '../sources/types'

export type ProgressFn = (p: { phase: string; done: number; total: number }) => void

export interface OpenedDataset {
  /** Everything views need from a dataset. A provider may implement it with plain HTTP calls. */
  api: DatasetApi
  /** Releases resources (e.g. terminates the worker). */
  close(): void
}

export type RemoteProviderId = 'dev' | 'api'

/** A remote service that serves datasets and run bundles by id (dev middleware, backend API…). */
export interface RemoteProvider {
  id: RemoteProviderId
  /** False when not configured (no VITE_API_URL, or not a dev server). */
  enabled(): boolean
  listDatasets(): Promise<{ id: string; name: string }[]>
  openDataset(id: string, name: string, onProgress: ProgressFn): Promise<OpenedDataset>
  listRuns(dataset: DatasetMeta): Promise<{ id: string; label: string }[]>
  loadRun(runId: string, dataset: DatasetMeta): Promise<RunBundle>
  /** Only providers that can run the agent (the backend). */
  startRun?(dataset: DatasetMeta): Promise<string>
  subscribeRun?(runId: string, onEvent: (e: MessageEvent) => void): () => void
}

/** How to reopen a dataset after a reload (persisted in IndexedDB). */
export type DatasetOrigin = { provider: 'local'; source: SourceDescriptor } | { provider: RemoteProviderId; id: string; name: string }
