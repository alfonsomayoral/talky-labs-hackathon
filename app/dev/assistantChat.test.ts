// @vitest-environment node
import { PassThrough } from 'node:stream'
import type { IncomingMessage, ServerResponse } from 'node:http'
import { describe, expect, it, vi } from 'vitest'
import { createAssistantChatHandler } from './assistantChat.ts'

const openAiStream = (...events: unknown[]) =>
  new Response(new ReadableStream({ start: (c) => (events.forEach((e) => c.enqueue(new TextEncoder().encode(`event: x\ndata: ${JSON.stringify(e)}\n\n`))), c.close()) }))

function call(handler: ReturnType<typeof createAssistantChatHandler>, method: string, url: string, body?: unknown) {
  const req = Object.assign(new PassThrough(), { method, url }) as unknown as IncomingMessage
  let out = ''
  const res = { statusCode: 200, setHeader: () => {}, writeHead: () => {}, write: (s: string) => (out += s), end: (s?: string) => (out += s ?? '') } as unknown as ServerResponse
  const done = handler(req, res, () => (out = 'NEXT'))
  ;(req as unknown as PassThrough).end(body === undefined ? undefined : JSON.stringify(body))
  return done.then(() => out)
}

describe('dev /api/chat', () => {
  it('re-emits the model deltas as SSE and keeps the key on the server', async () => {
    const fetchMock = vi.fn(async () => openAiStream({ type: 'response.output_text.delta', delta: 'Quedan ' }, { type: 'response.output_text.delta', delta: '56.' }, { type: 'response.completed' }))
    const out = await call(createAssistantChatHandler({ apiKey: 'sk-secret', model: 'm' }, fetchMock as unknown as typeof fetch), 'POST', '/api/chat', {
      messages: [{ role: 'user', content: '¿Qué reviso?' }],
      context: { text: 'Quedan 56 partidas' },
    })
    expect(out).toBe('event: delta\ndata: {"text":"Quedan "}\n\nevent: delta\ndata: {"text":"56."}\n\nevent: done\ndata: {}\n\n')
    expect(out).not.toContain('sk-secret')
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit]
    expect(url).toBe('https://api.openai.com/v1/responses')
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer sk-secret')
    expect(JSON.parse(init.body as string).input.at(-1).content).toContain('Quedan 56 partidas')
  })

  it('reports whether a model is configured and leaves other routes alone', async () => {
    expect(JSON.parse(await call(createAssistantChatHandler({ model: 'm' }), 'GET', '/api/chat/status'))).toEqual({ enabled: false, model: 'm' })
    expect(await call(createAssistantChatHandler({ apiKey: 'k' }), 'GET', '/otra')).toBe('NEXT')
  })

  it('turns a model error into an SSE error event', async () => {
    const fetchMock = vi.fn(async () => openAiStream({ type: 'error', error: { message: 'cuota agotada' } }))
    const out = await call(createAssistantChatHandler({ apiKey: 'k' }, fetchMock as unknown as typeof fetch), 'POST', '/api/chat', { messages: [] })
    expect(out).toBe('event: error\ndata: {"text":"cuota agotada"}\n\n')
  })
})
