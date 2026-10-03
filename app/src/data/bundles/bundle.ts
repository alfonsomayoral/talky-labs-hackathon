// Run bundles from loose JSONL files, a bundle folder (deliverables/, trace/, manifest.json)
// or a zip of either. Missing deliverables are kept as absent (`present[task] = false`).
import { unzipSync } from 'fflate'
import {
  DELIVERABLE_FILES,
  TASK_KEYS,
  type AgentEvent,
  type AttentionItem,
  type Deliverables,
  type RunBundle,
  type RunManifest,
  type RunSource,
  type TaskKey,
} from '@/domain/types'
import { parseJsonlText } from '../parsers/jsonl'
import { blobText } from '../parsers/text'
import { directoryHandleFiles } from '../sources/fileSystemSource'
import { isJunk, normalizePath } from '../sources/root'
import type { PathFile } from '../sources/types'
import { normalizeManifest } from './manifest'

const isZip = (name: string) => name.toLowerCase().endsWith('.zip')
const fileName = (p: string) => p.split('/').pop() ?? p
const dirName = (p: string) => p.split('/').slice(0, -1).join('/')

export function unzipFiles(data: Uint8Array): PathFile[] {
  return Object.entries(unzipSync(data))
    .filter(([path]) => !path.endsWith('/'))
    .map(([path, bytes]) => ({ path, file: new Blob([bytes as Uint8Array<ArrayBuffer>]) }))
}

/** Normalizes any import input into path + blob pairs and a suggested name. */
export async function runFilesFromInput(input: File[] | File | FileSystemDirectoryHandle): Promise<{ files: PathFile[]; name: string | null }> {
  if (input instanceof Blob) input = [input]
  if (!Array.isArray(input)) return { files: await directoryHandleFiles(input), name: input.name }
  const files: PathFile[] = []
  let name: string | null = null
  for (const f of input) {
    const path = f.webkitRelativePath || f.name
    if (isZip(f.name)) {
      files.push(...unzipFiles(new Uint8Array(await f.arrayBuffer())))
      name ??= f.name.replace(/\.zip$/i, '')
    } else {
      files.push({ path, file: f })
      if (path.includes('/')) name ??= path.split('/')[0]
    }
  }
  return { files, name }
}

/** Root of the bundle: the folder holding deliverables/ (or the loose JSONL), shallowest first. */
function bundleRoot(paths: string[]): string | null {
  const names = new Set(Object.values(DELIVERABLE_FILES))
  const roots = paths
    .filter((p) => names.has(fileName(p)))
    .map((p) => {
      const dir = dirName(p)
      return fileName(dir) === 'deliverables' ? dirName(dir) : dir
    })
  if (!roots.length) return null
  const depth = (r: string) => (r ? r.split('/').length : 0)
  return roots.sort((a, b) => depth(a) - depth(b) || a.localeCompare(b))[0]
}

export interface BundleOptions {
  datasetId: string
  source: RunSource
  label?: string
  /** Name of the folder or zip, used for the id and label when there is no manifest. */
  name?: string | null
  /** Forces the run id key (e.g. the API run id). */
  key?: string
}

const slug = (s: string) => s.replace(/[^A-Za-z0-9_.-]+/g, '-').replace(/^-+|-+$/g, '') || 'run'

async function parseFile<T>(file: PathFile): Promise<T[]> {
  try {
    return parseJsonlText<T>(await blobText(file.file))
  } catch (e) {
    throw new Error(`${file.path}: ${e instanceof Error ? e.message : String(e)}`)
  }
}

export async function bundleFromFiles(input: PathFile[], options: BundleOptions): Promise<RunBundle> {
  const files = input.map((f) => ({ ...f, path: normalizePath(f.path) })).filter((f) => !isJunk(f.path))
  const byPath = new Map(files.map((f) => [f.path, f]))
  const root = bundleRoot(files.map((f) => f.path))
  if (root === null) throw new Error(`No hay ninguna de las 6 entregas (${Object.values(DELIVERABLE_FILES).join(', ')})`)
  const at = (...rel: string[]) => rel.map((r) => byPath.get(root ? `${root}/${r}` : r)).find(Boolean) ?? null

  const deliverables = {} as Record<TaskKey, unknown[]>
  const present = {} as Record<TaskKey, boolean>
  for (const task of TASK_KEYS) {
    const file = at(`deliverables/${DELIVERABLE_FILES[task]}`, DELIVERABLE_FILES[task])
    present[task] = file !== null
    deliverables[task] = file ? await parseFile(file) : []
  }
  const manifestFile = at('manifest.json', 'run.json')
  let manifest: RunManifest | null = null
  if (manifestFile) {
    try {
      manifest = normalizeManifest(JSON.parse(await blobText(manifestFile.file)))
    } catch (e) {
      throw new Error(`${manifestFile.path}: ${e instanceof Error ? e.message : String(e)}`)
    }
  }
  const eventsFile = at('trace/events.jsonl', 'events.jsonl')
  const attentionFile = at('trace/attention.jsonl', 'attention.jsonl')

  const name = options.name ?? (root ? fileName(root) : null)
  const key = options.key ?? manifest?.run_id ?? name ?? `import-${Date.now().toString(36)}`
  return {
    id: `${options.datasetId}.${slug(key)}`,
    datasetId: options.datasetId,
    source: options.source,
    label: options.label ?? manifest?.run_id ?? name ?? `Importación ${new Date().toLocaleString('es-ES')}`,
    createdAt: new Date().toISOString(),
    manifest,
    deliverables: deliverables as unknown as Deliverables,
    present,
    events: eventsFile ? await parseFile<AgentEvent>(eventsFile) : null,
    attention: attentionFile ? await parseFile<AttentionItem>(attentionFile) : null,
  }
}
