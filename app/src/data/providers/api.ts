// Backend provider: the HTTP API `/v1` of `kalmora serve` (backend docs/api-contracts.md §9), enabled when
// VITE_API_URL is set. Phases and run bundles come as raw files (`…/files/__index.json` and `…/files/{path}`)
// and are parsed in the browser worker, like the dev middleware. The backend does not launch closes yet:
// runs are produced with its CLI and listed here once their bundle folder exists.
import type { DatasetMeta } from '@/domain/types'
import { bundleFromFiles } from '../bundles/bundle'
import type { PathFile } from '../sources/types'
import { openDataset } from '../worker/client'
import { encodePath, fetchJsonOrNull } from './http'
import type { RemoteProvider } from './types'

export const apiUrl = (): string | null => {
  const url = import.meta.env.VITE_API_URL as string | undefined
  return url ? url.replace(/\/+$/, '') : null
}

const v1 = () => {
  const api = apiUrl()
  if (!api) throw new Error('VITE_API_URL no está definida: no hay backend configurado')
  return `${api}/v1`
}

/** `data` of a `/v1` envelope, or null when the endpoint is missing. */
const data = async <T>(url: string): Promise<T | null> => (await fetchJsonOrNull<{ data: T }>(url))?.data ?? null

interface RunRow {
  run_id: string
  started_at?: string
  status?: string
  has_files?: boolean
}

/** Files of a run bundle; the run report becomes manifest.json when the bundle has none. */
async function runFiles(runId: string): Promise<PathFile[]> {
  const base = `${v1()}/runs/${encodeURIComponent(runId)}`
  const index = await fetchJsonOrNull<{ path: string }[]>(`${base}/files/__index.json`)
  if (!index) throw new Error(`El backend no tiene la ejecución ${runId}`)
  const wanted = index.filter((f) => /\.(jsonl|json)$/.test(f.path))
  const files = await Promise.all(wanted.map(async (f) => ({ path: f.path, file: await (await fetch(`${base}/files/${encodePath(f.path)}`)).blob() })))
  if (!wanted.some((f) => f.path === 'manifest.json')) {
    const report = await data<unknown>(base)
    if (report) files.push({ path: 'manifest.json', file: new Blob([JSON.stringify(report)], { type: 'application/json' }) })
  }
  return files
}

export const apiProvider: RemoteProvider = {
  id: 'api',
  enabled: () => apiUrl() !== null,

  async listDatasets() {
    const phases = await data<{ phase: string; month: string }[]>(`${v1()}/phases`)
    return (phases ?? []).map((p) => ({ id: p.phase, name: `${p.phase} · ${p.month}` }))
  },

  openDataset: (id, name, onProgress) =>
    openDataset({ kind: 'http', baseUrl: `${v1()}/phases/${encodeURIComponent(id)}/files`, name }, { remoteId: id }, onProgress),

  async listRuns() {
    const page = await data<{ items: RunRow[] }>(`${v1()}/runs?limit=1000`)
    return (page?.items ?? [])
      .filter((r) => r.has_files)
      .map((r) => ({ id: r.run_id, label: r.started_at ? `${r.run_id.slice(0, 8)} · ${r.started_at.slice(0, 16).replace('T', ' ')}` : r.run_id }))
  },

  loadRun: async (runId, dataset: DatasetMeta) => bundleFromFiles(await runFiles(runId), { datasetId: dataset.id, source: 'api', key: runId, name: runId }),
}
