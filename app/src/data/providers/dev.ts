// Dev provider: the Vite middleware (dev/kalmoraData.ts) serving local phase folders under
// /__data/<id>/ and run bundles under /__runs/<id>/. Files are parsed in the browser worker.
import type { DatasetMeta, RunBundle } from '@/domain/types'
import { bundleFromFiles } from '../bundles/bundle'
import type { PathFile } from '../sources/types'
import { openDataset } from '../worker/client'
import { absoluteUrl, encodePath, fetchJsonOrNull } from './http'
import type { RemoteProvider } from './types'

async function runFiles(folder: string): Promise<PathFile[]> {
  const base = `/__runs/${encodeURIComponent(folder)}`
  const index = await fetchJsonOrNull<{ path: string }[]>(`${base}/__index.json`)
  if (!index) throw new Error(`No se encuentra la ejecución ${folder} en /__runs`)
  const wanted = index.filter((f) => /\.(jsonl|json)$/.test(f.path))
  return Promise.all(wanted.map(async (f) => ({ path: f.path, file: await (await fetch(`${base}/${encodePath(f.path)}`)).blob() })))
}

export const devProvider: RemoteProvider = {
  id: 'dev',
  enabled: () => import.meta.env.DEV,
  listDatasets: async () => (await fetchJsonOrNull<{ id: string; name: string }[]>('/__data')) ?? [],
  openDataset: (id, name, onProgress) =>
    openDataset({ kind: 'http', baseUrl: absoluteUrl(`/__data/${encodeURIComponent(id)}`), name }, { remoteId: id }, onProgress),
  listRuns: async () => ((await fetchJsonOrNull<{ id: string; name: string }[]>('/__runs')) ?? []).map((r) => ({ id: r.id, label: r.name })),
  loadRun: async (folder: string, dataset: DatasetMeta): Promise<RunBundle> =>
    bundleFromFiles(await runFiles(folder), { datasetId: dataset.id, source: 'import', name: folder }),
}
