// JSON Lines: streaming parser for big files and a plain-text variant for small ones.
// Blank lines are skipped and CRLF endings are accepted.

export class JsonlError extends Error {
  readonly line: number
  constructor(line: number, cause: unknown) {
    super(`JSON inválido en la línea ${line}: ${cause instanceof Error ? cause.message : String(cause)}`)
    this.name = 'JsonlError'
    this.line = line
  }
}

function parseLine<T>(raw: string, lineNo: number): T | undefined {
  const line = raw.endsWith('\r') ? raw.slice(0, -1) : raw
  if (!line.trim()) return undefined
  try {
    return JSON.parse(line) as T
  } catch (e) {
    throw new JsonlError(lineNo, e)
  }
}

export function parseJsonlText<T>(text: string): T[] {
  const out: T[] = []
  const lines = text.split('\n')
  for (let i = 0; i < lines.length; i++) {
    const row = parseLine<T>(lines[i], i + 1)
    if (row !== undefined) out.push(row)
  }
  return out
}

/** Streams a JSONL blob row by row (Blob.stream + TextDecoderStream). Returns the row count. */
export async function streamJsonl<T>(blob: Blob, onRow: (row: T) => void, onBytes?: (bytes: number) => void): Promise<number> {
  const reader = blob.stream().pipeThrough(new TextDecoderStream()).getReader()
  let buffer = ''
  let lineNo = 0
  let rows = 0
  let chars = 0
  const emit = (raw: string) => {
    lineNo++
    const row = parseLine<T>(raw, lineNo)
    if (row !== undefined) {
      rows++
      onRow(row)
    }
  }
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += value
    chars += value.length
    let start = 0
    let nl = buffer.indexOf('\n')
    while (nl !== -1) {
      emit(buffer.slice(start, nl))
      start = nl + 1
      nl = buffer.indexOf('\n', start)
    }
    buffer = buffer.slice(start)
    onBytes?.(chars)
  }
  if (buffer) emit(buffer)
  return rows
}

export async function parseJsonlBlob<T>(blob: Blob): Promise<T[]> {
  const out: T[] = []
  await streamJsonl<T>(blob, (row) => out.push(row))
  return out
}
