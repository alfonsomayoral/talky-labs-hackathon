// Node built-ins for `// @vitest-environment node` tests. Loaded through a non-literal
// dynamic import so @types/node never enters the app program (it would retype
// setTimeout & co. for every browser module).

export interface NodeFs {
  existsSync(path: string): boolean
  readFileSync(path: string, encoding: 'utf8'): string
  writeFileSync(path: string, data: string): void
  readdirSync(path: string): string[]
  mkdirSync(path: string, opts?: { recursive?: boolean }): void
  mkdtempSync(prefix: string): string
  rmSync(path: string, opts?: { recursive?: boolean; force?: boolean }): void
  statSync(path: string): { isDirectory(): boolean }
}

export interface NodePath {
  join(...parts: string[]): string
  resolve(...parts: string[]): string
  dirname(path: string): string
}

export interface NodeChildProcess {
  spawnSync(cmd: string, args: string[], opts?: { encoding?: 'utf8'; timeout?: number }): { status: number | null; stdout: string; stderr: string; error?: Error }
}

export interface NodeEnv {
  fs: NodeFs
  path: NodePath
  cp: NodeChildProcess
  tmpdir: string
  cwd: string
  env: Record<string, string | undefined>
}

const load = (id: string): Promise<unknown> => import(/* @vite-ignore */ id)

export async function nodeEnv(): Promise<NodeEnv> {
  const [fs, path, cp, os] = await Promise.all(['node:fs', 'node:path', 'node:child_process', 'node:os'].map(load))
  const proc = (globalThis as unknown as { process: { cwd(): string; env: Record<string, string | undefined> } }).process
  return {
    fs: fs as NodeFs,
    path: path as NodePath,
    cp: cp as NodeChildProcess,
    tmpdir: (os as { tmpdir(): string }).tmpdir(),
    cwd: proc.cwd(),
    env: proc.env,
  }
}
