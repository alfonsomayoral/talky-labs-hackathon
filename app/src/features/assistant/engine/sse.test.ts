import { askAssistant } from './provider'
import { normalizeCard, readSse, streamChat } from './sse'
import type { AssistantContext } from './types'

const encoder = new TextEncoder()

/** A text/event-stream body delivered in arbitrary chunks (split inside lines and events). */
function sseBody(chunks: string[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(encoder.encode(c))
      controller.close()
    },
  })
}

const STREAM = [
  'event: delta\ndata: {"text": "Quedan 3 partidas "}\n\n',
  ': keep-alive\n\nevent: del',
  'ta\ndata: "pendientes."\n\n',
  'event: card\ndata: {"type": "metric", "metrics": [{"label": "Pendientes", "value": 3}]}\n\n',
  'event: card\ndata: {"type": "items", "title": "Por dónde empezar", "items": ["ap:API004128", {"item": "ap:API004151", "priority": "P0", "amount": 4202872, "currency": "EUR"}]}\n\n',
  'event: card\r\ndata: {"type": "table", "columns": ["Prioridad", {"label": "Partidas", "align": "right"}],\r\ndata: "rows": [["P0", 1], ["P2", 2]]}\r\n\r\n',
  'event: card\ndata: {"type": "chart", "x": 1}\n\n',
  'event: citation\ndata: {"item": "ap:API004128"}\n\n',
  'event: citation\ndata: {"policy_ref": "§2.2.3"}\n\n',
  'event: done\n\n',
  'event: delta\ndata: "ignorado"\n\n',
]

function fakeFetch(chunks: string[], status = 200) {
  return vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => new Response(sseBody(chunks), { status, headers: { 'Content-Type': 'text/event-stream' } }))
}

describe('readSse', () => {
  it('parses events split across chunks, CRLF, comments and multi-line data', async () => {
    const out = []
    for await (const m of readSse(sseBody(['data: a\n', 'data: b\n\nevent: x\nda', 'ta: 1\r\n\r\n', 'event: done\n\n']))) out.push(m)
    expect(out).toEqual([
      { event: 'message', data: 'a\nb' },
      { event: 'x', data: '1' },
      { event: 'done', data: '' },
    ])
  })
})

describe('streamChat against a fake SSE server', () => {
  it('folds deltas, cards and citations into one answer and stops at done', async () => {
    const fetch = fakeFetch(STREAM)
    const updates: number[] = []
    const answer = await streamChat(
      'http://api.test',
      { run_id: 'r1', dataset_id: 'd1', messages: [{ role: 'user', content: '¿Qué reviso?' }], mode: 'fast' },
      { fetch, onUpdate: (a) => updates.push(a.cards.length) },
    )
    expect(fetch).toHaveBeenCalledOnce()
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('http://api.test/api/chat')
    expect(init?.method).toBe('POST')
    expect(JSON.parse(String(init?.body))).toEqual({ run_id: 'r1', dataset_id: 'd1', messages: [{ role: 'user', content: '¿Qué reviso?' }], mode: 'fast' })

    expect(answer.source).toBe('api')
    expect(answer.text).toBe('Quedan 3 partidas pendientes.')
    expect(answer.cards).toEqual([
      { type: 'metric', title: undefined, metrics: [{ label: 'Pendientes', value: { kind: 'number', value: 3 }, delta: undefined, comparison: undefined, hint: undefined }] },
      {
        type: 'items',
        title: 'Por dónde empezar',
        total: undefined,
        items: [{ item: 'ap:API004128' }, { item: 'ap:API004151', title: undefined, amount: 4202872, currency: 'EUR', priority: 'P0', status: undefined }],
      },
      {
        type: 'table',
        title: undefined,
        columns: [{ label: 'Prioridad' }, { label: 'Partidas', align: 'right' }],
        rows: [
          [{ kind: 'text', text: 'P0' }, { kind: 'number', value: 1 }],
          [{ kind: 'text', text: 'P2' }, { kind: 'number', value: 2 }],
        ],
      },
    ])
    expect(answer.citations).toEqual([{ item: 'ap:API004128' }, { policy_ref: '§2.2.3' }])
    expect(updates.at(-1)).toBe(3)
  })

  it('fails with the HTTP status when the backend refuses', async () => {
    await expect(streamChat('http://api.test', { run_id: 'r', dataset_id: 'd', messages: [], mode: 'deep' }, { fetch: fakeFetch([], 503) })).rejects.toThrow('503')
  })

  it('askAssistant uses the backend when a base URL is configured, with history and mode', async () => {
    const fetch = fakeFetch(['event: delta\ndata: hola\n\n', 'event: done\n\n'])
    const ctx = { run: { id: 'run-7' }, meta: { id: 'local-id', remoteId: 'remote-id' }, mode: 'deep' } as unknown as AssistantContext
    const answer = await askAssistant('¿Y el balance?', ctx, { baseUrl: 'http://api.test', fetch, history: [{ role: 'user', content: 'Hola' }] })
    expect(answer.text).toBe('hola')
    expect(JSON.parse(String(fetch.mock.calls[0][1]?.body))).toEqual({
      run_id: 'run-7',
      dataset_id: 'remote-id',
      messages: [
        { role: 'user', content: 'Hola' },
        { role: 'user', content: '¿Y el balance?' },
      ],
      mode: 'deep',
    })
  })
})

describe('normalizeCard', () => {
  it('keeps reasoning and process cards and drops malformed ones', () => {
    expect(normalizeCard({ type: 'reasoning', item: 'ap:A1', headline: 'Se contabiliza.' })).toEqual({ type: 'reasoning', item: 'ap:A1', headline: 'Se contabiliza.', facts: [], steps: [] })
    expect(normalizeCard({ type: 'process', task: 'ap' })).toEqual({ type: 'process', task: 'ap' })
    expect(normalizeCard({ type: 'reasoning' })).toBeNull()
    expect(normalizeCard({ type: 'items', items: [] })).toBeNull()
    expect(normalizeCard('texto')).toBeNull()
  })
})
