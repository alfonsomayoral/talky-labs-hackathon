import type { DatasetMeta } from '@/domain/types'
import { deriveRun } from '@/engine'
import { fixtureCore, fixtureRun } from '@/features/item/kit/testing/fixture'
import { answerLocally } from './local'
import { askAssistant } from './provider'
import type { AssistantContext } from './types'

const core = fixtureCore()
const run = fixtureRun()
const ctx: AssistantContext = { data: deriveRun(core, run, null), core, meta: { id: 'fixture', name: 'Fixture', month: core.tasks.close.month } as DatasetMeta, run, overrides: [], mode: 'deep' }
const question = '¿Qué partidas tengo que revisar?'

const sse = (text: string) => new Response(`event: delta\ndata: ${JSON.stringify({ text })}\n\nevent: done\ndata: {}\n\n`)

describe('askAssistant in «Profundo» with the dev model', () => {
  it('lets the model write the text and keeps the local figures, cards and citations', async () => {
    const bodies: unknown[] = []
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (url === '/api/chat/status') return Response.json({ enabled: true, model: 'gpt-6-luna' })
      bodies.push(JSON.parse(String(init?.body)))
      return sse('Empieza por las dos de posible fraude.')
    })
    const local = answerLocally(question, ctx)
    const answer = await askAssistant(question, ctx, { fetch: fetchMock as unknown as typeof fetch })
    expect(answer.text).toBe('Empieza por las dos de posible fraude.')
    expect(answer.cards).toEqual(local.cards)
    expect(answer.citations).toEqual(local.citations)
    expect((bodies[0] as { context: { text: string } }).context.text).toBe(local.text)
  })

  it('falls back to the local answer when the model fails, and never calls it in «Rápido»', async () => {
    const fetchMock = vi.fn(async (url: string) => (url === '/api/chat/status' ? Response.json({ enabled: true, model: 'm' }) : new Response('', { status: 500 })))
    const local = answerLocally(question, ctx)
    expect((await askAssistant(question, ctx, { fetch: fetchMock as unknown as typeof fetch })).text).toBe(local.text)
    const calls = fetchMock.mock.calls.length
    await askAssistant(question, { ...ctx, mode: 'fast' }, { fetch: fetchMock as unknown as typeof fetch })
    expect(fetchMock.mock.calls.length).toBe(calls)
  })
})
