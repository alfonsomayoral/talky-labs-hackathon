// A phase folder zipped (any nesting). Entries are decompressed on demand.
import { unzipSync } from 'fflate'
import type { RawSource } from './types'
import { createRootedSource } from './root'

export function zipEntries(data: Uint8Array): { path: string; size: number }[] {
  const out: { path: string; size: number }[] = []
  unzipSync(data, {
    filter: (f) => {
      if (!f.name.endsWith('/')) out.push({ path: f.name, size: f.originalSize })
      return false
    },
  })
  return out
}

export function readZipEntry(data: Uint8Array, name: string): Uint8Array {
  const hit = unzipSync(data, { filter: (f) => f.name === name })[name]
  if (!hit) throw new Error(`No existe ${name} en el zip`)
  return hit
}

export async function zipSource(zip: Blob, zipName: string): Promise<RawSource> {
  const data = new Uint8Array(await zip.arrayBuffer())
  const fallback = zipName.replace(/\.zip$/i, '') || 'dataset'
  return createRootedSource('zip', zipEntries(data), async (p) => new Blob([readZipEntry(data, p) as Uint8Array<ArrayBuffer>]), fallback)
}
