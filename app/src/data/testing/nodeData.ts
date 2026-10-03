// Node-only helpers for tests that read the real datasets (they skip when the data is absent).
// node: modules are imported dynamically so the app tsconfig (DOM types only) stays untouched.
import type { PathFile } from '../sources/types'

interface NodeFs {
  existsSync(p: string): boolean
  readdirSync(p: string, o: { recursive: true }): string[]
  statSync(p: string): { isFile(): boolean; size: number }
  openAsBlob(p: string): Promise<Blob>
  readFileSync(p: string, enc: 'utf8'): string
}

export const nodeFs = (await import('node:fs' as string)) as NodeFs

/** From .env.local (KALMORA_DATASETS, via vitest.config.ts) or relative to app/ as in .env.example. */
const env = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env ?? {}
export const DEV_PHASE = env.KALMORA_DEV_PHASE ?? '../../participant/phase_dev'
export const TEST_PHASE = env.KALMORA_TEST_PHASE ?? '../../participant-2/phase_test'
export const hasDev = nodeFs.existsSync(`${DEV_PHASE}/tasks/close.json`)
export const hasTest = nodeFs.existsSync(`${TEST_PHASE}/tasks/close.json`)

export const readText = (path: string) => nodeFs.readFileSync(path, 'utf8')
export const readJsonl = <T>(path: string): T[] =>
  readText(path)
    .split('\n')
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l) as T)

/** Files under `dir` as PathFile, with paths prefixed by `prefix` (like webkitRelativePath). */
export async function dirFiles(dir: string, prefix: string): Promise<PathFile[]> {
  const rels = nodeFs.readdirSync(dir, { recursive: true }).map((r) => r.replace(/\\/g, '/'))
  const out: PathFile[] = []
  for (const rel of rels) {
    const abs = `${dir}/${rel}`
    if (!nodeFs.statSync(abs).isFile()) continue
    out.push({ path: prefix ? `${prefix}/${rel}` : rel, file: await nodeFs.openAsBlob(abs) })
  }
  return out
}
