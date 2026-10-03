// Files served over HTTP: `<baseUrl>/__index.json` lists `[{path, size}]` relative to the
// phase root and `<baseUrl>/<path>` serves each file (dev middleware /__data/<id>).
import type { FileEntry } from '@/domain/types'
import type { RawSource } from './types'
import { createRootedSource } from './root'

const encodePath = (p: string) => p.split('/').map(encodeURIComponent).join('/')

async function fetchOk(url: string): Promise<Response> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`HTTP ${res.status} al leer ${url}`)
  return res
}

export async function httpSource(baseUrl: string, name: string): Promise<RawSource> {
  const base = baseUrl.replace(/\/+$/, '')
  const index = (await (await fetchOk(`${base}/__index.json`)).json()) as FileEntry[]
  return createRootedSource('http', index, async (p) => (await fetchOk(`${base}/${encodePath(p)}`)).blob(), name)
}
