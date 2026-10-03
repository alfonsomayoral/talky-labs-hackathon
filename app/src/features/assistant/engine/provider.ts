// Picks the provider: the chat backend when VITE_CHAT_URL is set, the local deterministic engine otherwise.
// In development, «Profundo» can have a model write the text over the local answer (dev/assistantChat.ts):
// figures, cards and citations stay the local ones, so they match Resumen and Atención.

import { answerLocally } from './local'
import { apiBaseUrl, streamChat } from './sse'
import type { AssistantAnswer, AssistantContext, ChatMessage } from './types'

export interface AskOptions {
  /** Previous turns, oldest first (sent to the backend; the local engine answers each question alone). */
  history?: ChatMessage[]
  signal?: AbortSignal
  onUpdate?: (answer: AssistantAnswer) => void
  /** Overrides VITE_CHAT_URL (tests). `null` forces the local provider. */
  baseUrl?: string | null
  fetch?: typeof fetch
}

export const assistantProvider = (): 'api' | 'local' => (apiBaseUrl() ? 'api' : 'local')

export interface DevChatStatus {
  enabled: boolean
  model: string
}

let devChat: Promise<DevChatStatus | null> | null = null

/** The dev server's model for «Profundo», or null (no middleware, no key, or a production build). */
export function devChatStatus(doFetch: typeof fetch = fetch): Promise<DevChatStatus | null> {
  if (!import.meta.env.DEV) return Promise.resolve(null)
  devChat ??= doFetch('/api/chat/status')
    .then((r) => (r.ok ? (r.json() as Promise<DevChatStatus>) : null))
    .then((s) => (s?.enabled ? s : null))
    .catch(() => null)
  return devChat
}

let agent: Promise<DevChatStatus | null> | null = null

/** The model behind the chat backend (`GET /api/chat/status`), or null when it is not configured or unreachable. */
export function agentStatus(doFetch: typeof fetch = fetch): Promise<DevChatStatus | null> {
  const baseUrl = apiBaseUrl()
  if (!baseUrl) return Promise.resolve(null)
  agent ??= doFetch(`${baseUrl}/api/chat/status`)
    .then((r) => (r.ok ? (r.json() as Promise<DevChatStatus>) : null))
    .then((s) => (s?.enabled ? s : null))
    .catch(() => null)
  return agent
}

export async function askAssistant(question: string, ctx: AssistantContext, opts: AskOptions = {}): Promise<AssistantAnswer> {
  const baseUrl = opts.baseUrl === undefined ? apiBaseUrl() : opts.baseUrl
  if (!baseUrl) {
    const local = answerLocally(question, ctx)
    if (ctx.mode !== 'deep' || opts.baseUrl === null || !(await devChatStatus(opts.fetch))) return local
    try {
      const written = await streamChat(
        '',
        {
          run_id: ctx.run.id,
          dataset_id: ctx.meta.remoteId ?? ctx.meta.id,
          messages: [...(opts.history ?? []), { role: 'user', content: question }],
          mode: ctx.mode,
          context: { text: local.text, cards: local.cards, citations: local.citations },
        },
        { fetch: opts.fetch, signal: opts.signal, onUpdate: (p) => opts.onUpdate?.({ ...local, text: p.text, source: 'api' }) },
      )
      return written.text ? { ...local, text: written.text, source: 'api' } : local
    } catch {
      return local
    }
  }
  return streamChat(
    baseUrl,
    {
      run_id: ctx.run.id,
      dataset_id: ctx.meta.remoteId ?? ctx.meta.id,
      messages: [...(opts.history ?? []), { role: 'user', content: question }],
      mode: ctx.mode,
    },
    { fetch: opts.fetch, signal: opts.signal, onUpdate: opts.onUpdate },
  )
}
