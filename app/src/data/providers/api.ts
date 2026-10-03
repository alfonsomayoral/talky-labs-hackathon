// Backend provider: the HTTP API `/v1` of `kalmora serve` (backend docs/api-contracts.md §9), enabled when
// VITE_API_URL is set. Phases and run bundles come as raw files (`…/files/__index.json` and `…/files/{path}`)
// and are parsed in the browser worker, like the dev middleware. A phase is uploaded as the organizers' ZIP
// (`POST /v1/packages`); a close is launched with `POST /v1/phases/{phase}/runs` (the command given to
// `kalmora serve --close-command`) and followed by polling `GET /v1/runs/{id}`: the API has no event stream, so
// the live feed comes from the new lines the close command appends to the bundle's `trace/events.jsonl`.
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
  month?: string
}

const POLL_MS = 2000

/** Error message of a failed `/v1` call (RFC 9457 problem `detail`). */
async function failure(res: Response, action: string): Promise<Error> {
  const problem = (await res.json().catch(() => null)) as { detail?: string } | null
  return new Error(`${action}: ${problem?.detail ?? `el backend respondió ${res.status}`}`)
}

const EVENTS_FILE = 'trace/events.jsonl'

/** JSON objects of a JSONL chunk; a malformed line is skipped. */
const parseLines = (text: string): unknown[] =>
  text.split('\n').flatMap((line) => {
    if (!line.trim()) return []
    try {
      return [JSON.parse(line) as unknown]
    } catch {
      return []
    }
  })

const STATUS_LABEL: Record<string, string> = { running: ' · en curso', failed: ' · fallida' }

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

  async listRuns(dataset) {
    const page = await data<{ items: RunRow[] }>(`${v1()}/runs?limit=1000`)
    return (page?.items ?? [])
      .filter((r) => r.has_files && (!r.month || r.month === dataset.month))
      .map((r) => {
        const when = r.started_at ? ` · ${r.started_at.slice(0, 16).replace('T', ' ')}` : ''
        return { id: r.run_id, label: `${r.run_id.slice(0, 8)}${when}${STATUS_LABEL[r.status ?? ''] ?? ''}` }
      })
  },

  loadRun: async (runId, dataset: DatasetMeta) => bundleFromFiles(await runFiles(runId), { datasetId: dataset.id, source: 'api', key: runId, name: runId }),

  async startRun(dataset) {
    const res = await fetch(`${v1()}/phases/${encodeURIComponent(dataset.remoteId ?? dataset.id)}/runs`, { method: 'POST' })
    if (!res.ok) throw await failure(res, 'No se pudo lanzar el cierre')
    return ((await res.json()) as { data: { run_id: string } }).data.run_id
  },

  /** Polls the run until it ends: emits its new trace events while running, then `done`, or `error` with the reason. */
  subscribeRun(runId, onEvent) {
    const base = `${v1()}/runs/${encodeURIComponent(runId)}`
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let offset = 0
    /** Events appended since the last read; a trailing line still being written waits unless the run has ended. */
    const newEvents = async (ended: boolean): Promise<unknown[]> => {
      const index = await fetchJsonOrNull<{ path: string; size: number }[]>(`${base}/files/__index.json`)
      const file = index?.find((f) => f.path === EVENTS_FILE)
      if (!file || file.size <= offset) return []
      const res = await fetch(`${base}/files/${EVENTS_FILE}`, { headers: { Range: `bytes=${offset}-` } })
      if (!res.ok) return []
      const bytes = new Uint8Array(await res.arrayBuffer()).subarray(res.status === 206 ? 0 : offset)
      const end = ended ? bytes.length : bytes.lastIndexOf(10) + 1
      offset += end
      return parseLines(new TextDecoder().decode(bytes.subarray(0, end)))
    }
    const poll = async () => {
      const run = await data<{ status?: string; exit_code?: number }>(base).catch(() => null)
      if (stopped) return
      const ended = run?.status === 'completed' || run?.status === 'failed'
      if (run?.status === 'running' || ended) {
        const events = await newEvents(ended).catch(() => [])
        if (stopped) return
        // An empty batch still tells the tracker the run is under way.
        if (events.length || !ended) onEvent(new MessageEvent('message', { data: events }))
      }
      if (run?.status === 'completed') return onEvent(new MessageEvent('done', { data: '' }))
      if (run?.status === 'failed')
        return onEvent(new MessageEvent('error', { data: `El cierre ha fallado (código ${run.exit_code ?? '?'}); detalle en run.log de la ejecución` }))
      timer = setTimeout(() => void poll(), POLL_MS)
    }
    void poll()
    return () => {
      stopped = true
      clearTimeout(timer)
    }
  },

  /** Uploads the organizers' ZIP (root `participant/`) and waits until its phases are loaded. */
  async uploadDataset(file) {
    const form = new FormData()
    form.append('archive', file)
    const res = await fetch(`${v1()}/packages`, { method: 'POST', body: form })
    if (!res.ok) throw await failure(res, 'El backend rechazó el zip')
    const upload = ((await res.json()) as { data: { package_id: string; job_id: string | null; already_registered?: boolean } }).data
    if (upload.already_registered || !upload.job_id) {
      const phases = await data<{ phase: string; package_id: string }[]>(`${v1()}/phases`)
      return (phases ?? []).filter((p) => p.package_id === upload.package_id).map((p) => p.phase)
    }
    for (;;) {
      const job = await data<{ status: string; phases?: { phase: string }[]; error?: { detail?: string } }>(`${v1()}/jobs/${encodeURIComponent(upload.job_id)}`)
      if (!job || job.status === 'failed') throw new Error(`El backend no pudo cargar el zip${job?.error?.detail ? `: ${job.error.detail}` : ''}`)
      if (job.status === 'loaded') return (job.phases ?? []).map((p) => p.phase)
      await new Promise((r) => setTimeout(r, POLL_MS / 2))
    }
  },
}
