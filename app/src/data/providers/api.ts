// Backend provider (CONTRACT.md §2), enabled when VITE_API_URL is set.
// v1 assumption, not yet in the contract: a dataset's raw files are served under
// `GET /api/datasets/{id}/files/__index.json` and `…/files/{path}`, and parsed in the browser.
// When the backend serves parsed data, openDataset can return a DatasetApi made of HTTP calls.
import { DELIVERABLE_FILES, TASK_KEYS, type DatasetMeta, type RunManifest } from '@/domain/types'
import { bundleFromFiles } from '../bundles/bundle'
import type { PathFile } from '../sources/types'
import { openDataset } from '../worker/client'
import { encodePath, fetchJsonOrNull } from './http'
import type { RemoteProvider } from './types'

export const apiUrl = (): string | null => {
  const url = import.meta.env.VITE_API_URL as string | undefined
  return url ? url.replace(/\/+$/, '') : null
}

const requireApi = () => {
  const api = apiUrl()
  if (!api) throw new Error('VITE_API_URL no está definida: no hay backend configurado')
  return api
}

const remoteId = (dataset: DatasetMeta) => dataset.remoteId ?? dataset.id

/** Files of a run under `<runId>/` (the manifest from the status endpoint becomes manifest.json). */
async function runFiles(api: string, runId: string): Promise<PathFile[]> {
  const base = `${api}/api/runs/${encodeURIComponent(runId)}`
  const status = await fetchJsonOrNull<{ state?: string; manifest?: RunManifest }>(base)
  const paths = [...TASK_KEYS.map((t) => `deliverables/${DELIVERABLE_FILES[t]}`), 'trace/events.jsonl', 'trace/attention.jsonl']
  const files = (
    await Promise.all(
      paths.map(async (path) => {
        const res = await fetch(`${base}/files/${encodePath(path)}`)
        return res.ok ? { path: `${runId}/${path}`, file: await res.blob() } : null
      }),
    )
  ).filter((f): f is PathFile => f !== null)
  if (status?.manifest) files.push({ path: `${runId}/manifest.json`, file: new Blob([JSON.stringify(status.manifest)], { type: 'application/json' }) })
  return files
}

export const apiProvider: RemoteProvider = {
  id: 'api',
  enabled: () => apiUrl() !== null,

  async listDatasets() {
    const list = await fetchJsonOrNull<{ dataset_id: string; name?: string }[]>(`${requireApi()}/api/datasets`)
    return (list ?? []).map((d) => ({ id: d.dataset_id, name: d.name ?? d.dataset_id }))
  },

  openDataset: (id, name, onProgress) =>
    openDataset({ kind: 'http', baseUrl: `${requireApi()}/api/datasets/${encodeURIComponent(id)}/files`, name }, { remoteId: id }, onProgress),

  async listRuns(dataset) {
    const list = await fetchJsonOrNull<RunManifest[]>(`${requireApi()}/api/runs?dataset_id=${encodeURIComponent(remoteId(dataset))}`)
    return (list ?? []).map((m) => ({ id: m.run_id, label: m.finished_at ? `${m.run_id} · ${m.finished_at.slice(0, 16).replace('T', ' ')}` : m.run_id }))
  },

  loadRun: async (runId, dataset) => bundleFromFiles(await runFiles(requireApi(), runId), { datasetId: dataset.id, source: 'api', key: runId, name: runId }),

  async startRun(dataset) {
    const res = await fetch(`${requireApi()}/api/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dataset_id: remoteId(dataset), options: {} }),
    })
    if (!res.ok) throw new Error(`El backend respondió ${res.status} al lanzar el cierre`)
    return ((await res.json()) as { run_id: string }).run_id
  },

  subscribeRun(runId, onEvent) {
    const es = new EventSource(`${requireApi()}/api/runs/${encodeURIComponent(runId)}/events`)
    es.onmessage = onEvent
    es.addEventListener('done', (e) => {
      onEvent(e as MessageEvent)
      es.close()
    })
    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) onEvent(new MessageEvent('error', { data: 'Se ha cerrado la conexión con el backend' }))
    }
    return () => es.close()
  },
}
