// Locates the phase root (the folder that holds erp/ and tasks/) inside any selection,
// so users may pick the phase itself or a parent such as `participant/`.
import type { DatasetSourceKind, FileEntry } from '@/domain/types'
import { blobText } from '../parsers/text'
import type { RawSource } from './types'

export function normalizePath(p: string): string {
  return p.replace(/\\/g, '/').replace(/^(\.\/)+/, '').replace(/^\/+/, '')
}

/** Hidden files, macOS zip metadata and Python caches. */
export function isJunk(path: string): boolean {
  return path.split('/').some((s) => s.startsWith('.') || s === '__MACOSX' || s === '__pycache__')
}

/** Candidate roots, shallowest first. `''` means the selection itself is the phase folder. */
export function detectPhaseRoots(paths: string[]): string[] {
  const erp = new Set<string>()
  const tasks = new Set<string>()
  for (const p of paths) {
    const segs = p.split('/')
    for (let i = 0; i < segs.length - 1; i++) {
      if (segs[i] === 'erp') erp.add(segs.slice(0, i).join('/'))
      else if (segs[i] === 'tasks') tasks.add(segs.slice(0, i).join('/'))
    }
  }
  const depth = (r: string) => (r ? r.split('/').length : 0)
  return [...erp].filter((r) => tasks.has(r)).sort((a, b) => depth(a) - depth(b) || a.localeCompare(b))
}

const MIME: Record<string, string> = {
  pdf: 'application/pdf',
  xml: 'application/xml',
  json: 'application/json',
  jsonl: 'application/x-ndjson',
  csv: 'text/csv',
  n43: 'text/plain',
  txt: 'text/plain',
}

/** Blobs carry their media type so a PDF can go straight into an <iframe> via URL.createObjectURL. */
function typed(blob: Blob, path: string): Blob {
  const type = MIME[path.slice(path.lastIndexOf('.') + 1).toLowerCase()]
  return type && blob.type !== type ? new Blob([blob], { type }) : blob
}

export function createRootedSource(
  kind: DatasetSourceKind,
  all: FileEntry[],
  readFull: (fullPath: string) => Promise<Blob>,
  fallbackName: string,
): RawSource {
  const clean = all.map((e) => ({ ...e, path: normalizePath(e.path) })).filter((e) => !isJunk(e.path))
  const roots = detectPhaseRoots(clean.map((e) => e.path))
  if (!roots.length) throw new Error('No se encuentra la carpeta de una fase: debe contener erp/ y tasks/')
  const root = roots[0]
  const prefix = root ? `${root}/` : ''
  const entries = clean.filter((e) => e.path.startsWith(prefix)).map((e) => ({ ...e, path: e.path.slice(prefix.length) }))
  const known = new Set(entries.map((e) => e.path))
  const read = async (path: string) => {
    if (!known.has(path)) throw new Error(`No existe el fichero ${path}`)
    return typed(await readFull(prefix + path), path)
  }
  return {
    kind,
    name: root ? root.split('/').pop()! : fallbackName,
    notes: roots.length > 1 ? [`Hay varias fases en la selección; se usa «${root || '.'}» y se ignoran: ${roots.slice(1).join(', ')}`] : [],
    list: async () => entries,
    read,
    text: async (path) => blobText(await read(path)),
  }
}
