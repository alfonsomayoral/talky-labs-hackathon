// API provider: `POST {VITE_API_URL}/api/chat` answered by SSE (CONTRACT.md §2):
// `event: delta` text, `event: card` a card, `event: citation` {item} or {policy_ref}, `event: done`.
// The browser never holds model keys: the backend calls the models.

import type { AssistantAnswer, AssistantCard, CardItem, ChatMessage, ChatMode, Citation, MetricDatum, TableCell, TableColumn } from './types'

export interface SseMessage {
  event: string
  data: string
}

/** Splits a text/event-stream body into messages (event defaults to `message`; data lines are joined by a newline). */
export async function* readSse(body: ReadableStream<Uint8Array>): AsyncGenerator<SseMessage> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let event = 'message'
  let data: string[] = []
  const flush = (): SseMessage | null => {
    // A named event without data (`event: done`) is still delivered.
    const out = data.length || event !== 'message' ? { event, data: data.join('\n') } : null
    event = 'message'
    data = []
    return out
  }
  try {
    for (;;) {
      const { value, done } = await reader.read()
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true })
      const lines = buffer.split(/\r\n|\r|\n/)
      buffer = done ? '' : (lines.pop() ?? '')
      for (const line of lines) {
        if (line === '') {
          const msg = flush()
          if (msg) yield msg
        } else if (!line.startsWith(':')) {
          const i = line.indexOf(':')
          const field = i < 0 ? line : line.slice(0, i)
          const val = i < 0 ? '' : line.slice(i + 1).replace(/^ /, '')
          if (field === 'event') event = val
          else if (field === 'data') data.push(val)
        }
      }
      if (done) {
        const msg = flush()
        if (msg) yield msg
        return
      }
    }
  } finally {
    // Stops the body when the caller leaves early (`done` before the end of the stream).
    reader.cancel().catch(() => {})
  }
}

// ---------------------------------------------------------------- payload normalisation
type Json = Record<string, unknown>

const isObj = (x: unknown): x is Json => typeof x === 'object' && x !== null && !Array.isArray(x)
const str = (x: unknown): string | undefined => (typeof x === 'string' ? x : undefined)
const num = (x: unknown): number | undefined => (typeof x === 'number' && Number.isFinite(x) ? x : undefined)

function parseJson(data: string): unknown {
  try {
    return JSON.parse(data)
  } catch {
    return data
  }
}

function toCell(x: unknown): TableCell {
  if (isObj(x) && typeof x.kind === 'string') return x as unknown as TableCell
  if (typeof x === 'number') return { kind: 'number', value: x }
  return { kind: 'text', text: x == null ? '—' : String(x) }
}

function toMetric(x: unknown): MetricDatum | null {
  if (!isObj(x) || typeof x.label !== 'string') return null
  const v = x.value
  const value: MetricDatum['value'] = isObj(v) && typeof v.kind === 'string' ? (v as MetricDatum['value']) : typeof v === 'number' ? { kind: 'number', value: v } : { kind: 'text', text: String(v ?? '—') }
  return { label: x.label, value, delta: str(x.delta), comparison: str(x.comparison), hint: str(x.hint) }
}

function toItem(x: unknown): CardItem | null {
  if (typeof x === 'string') return { item: x }
  if (!isObj(x) || typeof x.item !== 'string') return null
  return { item: x.item, title: str(x.title), amount: num(x.amount) ?? null, currency: str(x.currency) ?? null, priority: x.priority as CardItem['priority'], status: x.status as CardItem['status'] }
}

const compact = <T>(xs: (T | null)[]): T[] => xs.filter((x): x is T => x !== null)

/** A card from the backend in the app's shape; unknown or malformed cards are dropped. */
export function normalizeCard(x: unknown): AssistantCard | null {
  if (!isObj(x)) return null
  const title = str(x.title)
  switch (x.type) {
    case 'metric': {
      const metrics = compact((Array.isArray(x.metrics) ? x.metrics : [x]).map(toMetric))
      return metrics.length ? { type: 'metric', title, metrics } : null
    }
    case 'table': {
      if (!Array.isArray(x.columns) || !Array.isArray(x.rows)) return null
      const columns: TableColumn[] = x.columns.map((c) => (isObj(c) ? { label: String(c.label ?? ''), align: c.align === 'right' ? 'right' : 'left' } : { label: String(c) }))
      const rows = x.rows.filter(Array.isArray).map((r: unknown[]) => r.map(toCell))
      return { type: 'table', title, columns, rows }
    }
    case 'items': {
      const items = compact((Array.isArray(x.items) ? x.items : []).map(toItem))
      return items.length ? { type: 'items', title, items, total: num(x.total) } : null
    }
    case 'reasoning':
      if (typeof x.item !== 'string') return null
      return { type: 'reasoning', item: x.item, headline: str(x.headline) ?? '', facts: Array.isArray(x.facts) ? x.facts : [], steps: Array.isArray(x.steps) ? x.steps : [] }
    case 'process':
      return typeof x.task === 'string' ? ({ type: 'process', task: x.task } as AssistantCard) : null
    default:
      return null
  }
}

export function normalizeCitation(x: unknown): Citation | null {
  if (!isObj(x)) return null
  if (typeof x.item === 'string') return { item: x.item }
  if (typeof x.policy_ref === 'string') return { policy_ref: x.policy_ref }
  return null
}

function deltaText(data: string): string {
  const v = parseJson(data)
  if (typeof v === 'string') return v
  if (isObj(v)) return str(v.text) ?? str(v.delta) ?? ''
  return data
}

// ---------------------------------------------------------------- request
export interface ChatRequest {
  run_id: string
  dataset_id: string
  messages: ChatMessage[]
  mode: ChatMode
  /** Dev extension: the local answer the model writes over (the dev /api/chat middleware). */
  context?: unknown
}

export interface StreamOptions {
  fetch?: typeof fetch
  signal?: AbortSignal
  /** Called with the answer so far after every event. */
  onUpdate?: (answer: AssistantAnswer) => void
}

/** Base URL of the backend, without trailing slash (null when VITE_API_URL is not set). */
export function apiBaseUrl(): string | null {
  const url = import.meta.env.VITE_API_URL as string | undefined
  return url ? url.replace(/\/+$/, '') : null
}

/** Asks the backend and folds the SSE stream into one answer. Resolves on `done` or at the end of the stream. */
export async function streamChat(baseUrl: string, req: ChatRequest, opts: StreamOptions = {}): Promise<AssistantAnswer> {
  const doFetch = opts.fetch ?? fetch
  const res = await doFetch(`${baseUrl}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(req),
    signal: opts.signal,
  })
  if (!res.ok || !res.body) throw new Error(`El backend respondió ${res.status} a la pregunta`)
  const answer: AssistantAnswer = { text: '', cards: [], citations: [], links: [], intent: null, source: 'api' }
  const emit = () => opts.onUpdate?.({ ...answer, cards: [...answer.cards], citations: [...answer.citations] })
  for await (const msg of readSse(res.body)) {
    if (msg.event === 'done') break
    if (msg.event === 'error') throw new Error(deltaText(msg.data) || 'El backend no pudo responder')
    if (msg.event === 'delta' || msg.event === 'message') answer.text += deltaText(msg.data)
    else if (msg.event === 'card') {
      const card = normalizeCard(parseJson(msg.data))
      if (card) answer.cards.push(card)
    } else if (msg.event === 'citation') {
      const c = normalizeCitation(parseJson(msg.data))
      if (c) answer.citations.push(c)
    } else continue
    emit()
  }
  return answer
}
