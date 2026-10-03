// Dev-only Vite middleware that serves local dataset folders under /__data/<id>/…
// and run bundles under /__runs/<id>/…. Never used in production builds.
import { createReadStream, existsSync, readdirSync, statSync } from 'node:fs'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { basename, extname, resolve, sep } from 'node:path'
import type { Plugin } from 'vite'

export interface KalmoraDataOptions {
  /** `dev:../../participant/phase_dev,test:../../participant-2/phase_test` */
  datasets?: string
  /** Folder that contains run bundles, e.g. `../runs`. */
  runs?: string
}

const RUN_FILES = ['ap.jsonl', 'ar_billing.jsonl', 'ar_cash.jsonl', 'bank_rec.jsonl', 'ic.jsonl', 'close.jsonl']

const CONTENT_TYPES: Record<string, string> = {
  '.json': 'application/json; charset=utf-8',
  '.jsonl': 'application/x-ndjson; charset=utf-8',
  '.pdf': 'application/pdf',
  '.xml': 'application/xml',
  '.csv': 'text/csv',
  '.n43': 'text/plain',
  '.txt': 'text/plain',
  '.md': 'text/markdown; charset=utf-8',
  '.zip': 'application/zip',
}

type Next = (err?: unknown) => void
export type KalmoraHandler = (req: IncomingMessage, res: ServerResponse, next: Next) => void

interface DatasetDir {
  id: string
  name: string
  path: string
  abs: string
}

export function parseDatasets(spec: string | undefined, cwd: string): DatasetDir[] {
  return (spec ?? '')
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean)
    .flatMap((part) => {
      const i = part.indexOf(':')
      if (i <= 0) return []
      const id = part.slice(0, i).trim()
      const path = part.slice(i + 1).trim()
      const abs = resolve(cwd, path)
      return [{ id, name: basename(abs), path, abs }]
    })
}

const isDir = (p: string) => existsSync(p) && statSync(p).isDirectory()
const hidden = (name: string) => name.startsWith('.') || name === '__pycache__' || name === '__MACOSX'

/** Recursive listing relative to `root`, `/`-separated, sorted. */
export function listTree(root: string): { path: string; size: number }[] {
  if (!isDir(root)) return []
  const out: { path: string; size: number }[] = []
  const walk = (dir: string, rel: string) => {
    for (const d of readdirSync(dir, { withFileTypes: true })) {
      if (hidden(d.name)) continue
      const abs = resolve(dir, d.name)
      const r = rel ? `${rel}/${d.name}` : d.name
      if (d.isDirectory()) walk(abs, r)
      else if (d.isFile()) out.push({ path: r, size: statSync(abs).size })
    }
  }
  walk(root, '')
  return out.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0))
}

function isRunBundle(dir: string): boolean {
  if (isDir(resolve(dir, 'deliverables'))) return true
  return RUN_FILES.some((f) => existsSync(resolve(dir, f)))
}

export function listRuns(runsRoot: string): { id: string; name: string; modifiedAt: string }[] {
  if (!isDir(runsRoot)) return []
  return readdirSync(runsRoot, { withFileTypes: true })
    .filter((d) => d.isDirectory() && !hidden(d.name) && isRunBundle(resolve(runsRoot, d.name)))
    .map((d) => {
      const st = statSync(resolve(runsRoot, d.name))
      return { id: d.name, name: d.name, modifiedAt: st.mtime.toISOString(), mtime: st.mtimeMs }
    })
    .sort((a, b) => b.mtime - a.mtime)
    .map(({ id, name, modifiedAt }) => ({ id, name, modifiedAt }))
}

function sendJson(res: ServerResponse, status: number, body: unknown) {
  const text = JSON.stringify(body)
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.setHeader('Cache-Control', 'no-store')
  res.end(text)
}

/** Resolves `rel` under `root`, or null when it escapes the root. */
export function safeJoin(root: string, rel: string): string | null {
  if (rel.includes('\0')) return null
  const segments = rel.split('/').filter((s) => s !== '' && s !== '.')
  if (segments.some((s) => s === '..' || s.includes('\\'))) return null
  const abs = resolve(root, ...segments)
  return abs === root || abs.startsWith(root + sep) ? abs : null
}

function sendFile(req: IncomingMessage, res: ServerResponse, abs: string) {
  if (!existsSync(abs) || !statSync(abs).isFile()) return sendJson(res, 404, { error: 'not found' })
  const st = statSync(abs)
  res.statusCode = 200
  res.setHeader('Content-Type', CONTENT_TYPES[extname(abs).toLowerCase()] ?? 'application/octet-stream')
  res.setHeader('Content-Length', String(st.size))
  res.setHeader('Cache-Control', 'no-cache')
  if (req.method === 'HEAD') return res.end()
  const stream = createReadStream(abs)
  stream.on('error', () => res.destroy())
  stream.pipe(res)
}

/** Serves `/__index.json` or a file below `root`. `rest` is the URL-decoded path after the id. */
function serveTree(req: IncomingMessage, res: ServerResponse, root: string, rest: string) {
  if (rest === '' || rest === '__index.json') return sendJson(res, 200, listTree(root))
  const abs = safeJoin(root, rest)
  if (!abs) return sendJson(res, 403, { error: 'forbidden path' })
  sendFile(req, res, abs)
}

export function createKalmoraHandler(options: KalmoraDataOptions, cwd: string): KalmoraHandler {
  const datasets = parseDatasets(options.datasets, cwd)
  const runsRoot = options.runs ? resolve(cwd, options.runs) : null

  return (req, res, next) => {
    const url = req.url ?? ''
    if (!url.startsWith('/__data') && !url.startsWith('/__runs')) return next()
    if (req.method !== 'GET' && req.method !== 'HEAD') return sendJson(res, 405, { error: 'method not allowed' })

    let pathname: string
    try {
      pathname = decodeURIComponent(new URL(url, 'http://localhost').pathname)
    } catch {
      return sendJson(res, 400, { error: 'bad url' })
    }
    const [, area, id, ...rest] = pathname.split('/')
    if (area !== '__data' && area !== '__runs') return next()

    if (area === '__data') {
      if (!id) return sendJson(res, 200, datasets.filter((d) => isDir(d.abs)).map(({ id, name, path }) => ({ id, name, path })))
      const ds = datasets.find((d) => d.id === id)
      if (!ds) return sendJson(res, 404, { error: `unknown dataset ${id}` })
      return serveTree(req, res, ds.abs, rest.join('/'))
    }

    if (!runsRoot) return sendJson(res, id ? 404 : 200, id ? { error: 'no runs folder' } : [])
    if (!id) return sendJson(res, 200, listRuns(runsRoot))
    const runDir = safeJoin(runsRoot, id)
    if (!runDir || id.includes('/')) return sendJson(res, 403, { error: 'forbidden path' })
    if (!isDir(runDir)) return sendJson(res, 404, { error: `unknown run ${id}` })
    return serveTree(req, res, runDir, rest.join('/'))
  }
}

export function kalmoraData(options: KalmoraDataOptions = {}): Plugin {
  return {
    name: 'kalmora-data',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use(createKalmoraHandler(options, process.cwd()))
    },
  }
}
