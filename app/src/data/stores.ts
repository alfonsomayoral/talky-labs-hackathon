// Public store API of the data layer (frozen contract — phase 1.B implements it).
// Views and the engine glue import ONLY from this module, never from data internals.

import { create } from 'zustand'
import type { DatasetApi, DatasetMeta, RunBundle } from '@/domain/types'
import * as db from './persist'
import {
  folderSource,
  importLocalRun,
  openLocal,
  remoteProviders,
  splitRunId,
  zipSourceOf,
  type DatasetOrigin,
  type OpenedDataset,
  type ProgressFn,
  type RemoteProviderId,
} from './providers'
import { goldenRun } from './bundles/golden'

/** Drag & drop helper: call it synchronously from onDrop; files carry their folder path. */
export { filesFromDataTransfer } from './sources/dataTransfer'

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

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const JOURNAL_PHASE = 'Indexando diario'

let opened: OpenedDataset | null = null
let loadSeq = 0
let session: db.Session = { datasetId: null, runs: {} }

const persistSession = () => {
  session = { ...session, datasetId: useDatasetStore.getState().activeId }
  return db.saveSession(session)
}

/** Opens a dataset through `open`, makes it active and remembers its origin. */
async function activateWith(origin: DatasetOrigin, open: (onProgress: ProgressFn) => Promise<OpenedDataset>): Promise<DatasetMeta> {
  const seq = ++loadSeq
  useDatasetStore.setState({ status: 'loading', progress: { phase: 'Abriendo', done: 0, total: 1 }, error: null })
  let next: OpenedDataset
  try {
    next = await open((p) => {
      if (seq !== loadSeq) return
      const { status } = useDatasetStore.getState()
      if (status === 'loading') useDatasetStore.setState({ progress: p })
      else if (p.phase === JOURNAL_PHASE) useDatasetStore.setState({ progress: p.done < p.total ? p : null })
    })
  } catch (e) {
    if (seq === loadSeq) useDatasetStore.setState({ status: 'error', progress: null, error: message(e) })
    throw e
  }
  const meta = next.api.meta
  if (seq !== loadSeq) {
    next.close()
    return meta
  }
  opened?.close()
  opened = next
  const datasets = [meta, ...useDatasetStore.getState().datasets.filter((d) => d.id !== meta.id)]
  useDatasetStore.setState({ api: next.api, activeId: meta.id, status: 'ready', progress: null, error: null, datasets })
  await Promise.all([db.saveDatasets(datasets), db.saveOrigin(meta.id, origin), persistSession()])
  return meta
}

const openOrigin = (origin: DatasetOrigin, id?: string) =>
  activateWith(origin, (onProgress) =>
    origin.provider === 'local' ? openLocal(origin.source, id ? { id } : {}, onProgress) : remoteProviders[origin.provider].openDataset(origin.id, origin.name, onProgress),
  )

export const useDatasetStore = create<DatasetState>()((set, get) => ({
  datasets: [],
  activeId: null,
  api: null,
  status: 'idle',
  progress: null,
  error: null,
  available: [],

  async refreshAvailable() {
    const out: DatasetState['available'] = []
    for (const provider of Object.values(remoteProviders)) {
      if (!provider.enabled()) continue
      const list = await provider.listDatasets().catch(() => [])
      for (const d of list) out.push({ id: d.id, name: d.name, source: provider.id })
    }
    set({ available: out })
  },

  loadFromFolder: (input) => openOrigin({ provider: 'local', source: folderSource(input) }),

  loadFromZip: (file) => openOrigin({ provider: 'local', source: zipSourceOf(file) }),

  async loadFromHttp(id) {
    if (!get().available.some((a) => a.id === id)) await get().refreshAvailable()
    const entry = get().available.find((a) => a.id === id)
    const provider: RemoteProviderId = entry?.source ?? 'dev'
    return openOrigin({ provider, id, name: entry?.name ?? id })
  },

  async activate(id) {
    if (get().activeId === id && get().api) return
    const origin = await db.loadOrigin(id)
    if (!origin) {
      const error = 'No se puede reabrir este dataset: vuelve a cargar la carpeta o el zip'
      set({ status: 'error', progress: null, error })
      throw new Error(error)
    }
    await openOrigin(origin, id)
  },

  async remove(id) {
    const datasets = get().datasets.filter((d) => d.id !== id)
    if (get().activeId === id) {
      loadSeq++
      opened?.close()
      opened = null
      set({ activeId: null, api: null, status: 'idle', progress: null, error: null })
    }
    set({ datasets })
    const runs = { ...session.runs }
    delete runs[id]
    session = { ...session, runs }
    await Promise.all([db.saveDatasets(datasets), db.forgetDataset(id), persistSession()])
  },
}))

// ---------------------------------------------------------------- runs

let runsReady: Promise<void> = Promise.resolve()

async function loadRunsFor(datasetId: string | null) {
  useRunStore.setState({ runs: [], activeId: null, status: 'idle', error: null })
  if (!datasetId) return
  const runs = await db.loadRuns(datasetId)
  if (useDatasetStore.getState().activeId !== datasetId) return
  const wanted = session.runs[datasetId] ?? null
  useRunStore.setState((s) => {
    const merged = [...s.runs, ...runs.filter((r) => !s.runs.some((x) => x.id === r.id))]
    const activeId = s.activeId ?? (merged.some((r) => r.id === wanted) ? wanted : null)
    return { runs: merged, activeId, status: merged.length ? 'ready' : 'idle' }
  })
}

useDatasetStore.subscribe((s, prev) => {
  if (s.activeId !== prev.activeId) runsReady = loadRunsFor(s.activeId)
})

function activeDataset(): DatasetApi {
  const api = useDatasetStore.getState().api
  if (!api) throw new Error('Carga primero un dataset')
  return api
}

async function addRun(bundle: RunBundle): Promise<RunBundle> {
  await runsReady
  if (useDatasetStore.getState().activeId !== bundle.datasetId) {
    const stored = await db.loadRuns(bundle.datasetId)
    await db.saveRuns(bundle.datasetId, [bundle, ...stored.filter((r) => r.id !== bundle.id)])
    return bundle
  }
  const runs = [bundle, ...useRunStore.getState().runs.filter((r) => r.id !== bundle.id)]
  useRunStore.setState({ runs, activeId: bundle.id, status: 'ready', error: null })
  session = { ...session, runs: { ...session.runs, [bundle.datasetId]: bundle.id } }
  await Promise.all([db.saveRuns(bundle.datasetId, runs), persistSession()])
  return bundle
}

async function tracked<T>(fn: () => Promise<T>): Promise<T> {
  useRunStore.setState({ status: 'loading', error: null })
  try {
    return await fn()
  } catch (e) {
    useRunStore.setState({ status: 'error', error: message(e) })
    throw e
  }
}

const datasetMeta = (datasetId: string) =>
  useDatasetStore.getState().datasets.find((d) => d.id === datasetId) ?? ({ id: datasetId } as DatasetMeta)

export const useRunStore = create<RunState>()((set, get) => ({
  runs: [],
  activeId: null,
  status: 'idle',
  error: null,

  createGoldenRun: () =>
    tracked(async () => {
      const api = activeDataset()
      if (!api.core.golden) throw new Error('Este dataset no tiene golden/: no hay referencia que abrir')
      return addRun(goldenRun(api.meta, api.core.golden))
    }),

  importRun: (input, label) => tracked(async () => addRun(await importLocalRun(input, activeDataset().meta, label))),

  async listRemoteRuns() {
    const meta = useDatasetStore.getState().api?.meta
    const out: { id: string; label: string; source: RemoteProviderId }[] = []
    if (!meta) return out
    for (const provider of Object.values(remoteProviders)) {
      if (!provider.enabled()) continue
      for (const r of await provider.listRuns(meta).catch(() => [])) out.push({ id: `${provider.id}:${r.id}`, label: r.label, source: provider.id })
    }
    return out
  },

  loadRemoteRun: (id) =>
    tracked(async () => {
      const meta = activeDataset().meta
      const { provider, runId } = splitRunId(id)
      if (!provider.enabled()) throw new Error(provider.id === 'api' ? 'VITE_API_URL no está definida: no hay backend del que leer la ejecución' : `El proveedor ${provider.id} no está disponible`)
      return addRun(await provider.loadRun(runId, meta))
    }),

  async startApiRun(datasetId) {
    const api = remoteProviders.api
    if (!api.enabled() || !api.startRun) throw new Error('VITE_API_URL no está definida: importa un paquete de ejecución')
    return api.startRun(datasetMeta(datasetId))
  },

  subscribeRun(runId, onEvent) {
    const api = remoteProviders.api
    if (!api.enabled() || !api.subscribeRun) {
      queueMicrotask(() => onEvent(new MessageEvent('error', { data: 'VITE_API_URL no está definida' })))
      return () => {}
    }
    return api.subscribeRun(splitRunId(runId).runId, onEvent)
  },

  setActive(id) {
    set({ activeId: id })
    const datasetId = useDatasetStore.getState().activeId
    if (datasetId) {
      session = { ...session, runs: { ...session.runs, [datasetId]: id } }
      void persistSession()
    }
  },

  async remove(id) {
    const run = get().runs.find((r) => r.id === id)
    const runs = get().runs.filter((r) => r.id !== id)
    set({ runs, status: runs.length ? 'ready' : 'idle' })
    if (get().activeId === id) get().setActive(null)
    if (run) await db.saveRuns(run.datasetId, runs)
  },
}))

// ---------------------------------------------------------------- session restore

async function restoreSession() {
  const [stored, saved] = await Promise.all([db.loadDatasets(), db.loadSession()])
  session = saved
  useDatasetStore.setState((s) => ({ datasets: [...s.datasets, ...stored.filter((d) => !s.datasets.some((x) => x.id === d.id))] }))
  const { activeId, status } = useDatasetStore.getState()
  if (saved.datasetId && !activeId && status !== 'loading' && stored.some((d) => d.id === saved.datasetId))
    await useDatasetStore
      .getState()
      .activate(saved.datasetId)
      .catch(() => undefined)
}

/** Resolves once the persisted session (datasets list, active dataset and run) has been restored. */
export const sessionRestored: Promise<void> = typeof window !== 'undefined' && db.persistenceAvailable() ? restoreSession() : Promise.resolve()
