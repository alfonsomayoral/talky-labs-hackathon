// Picks the provider: the backend when VITE_API_URL is set, the local deterministic engine otherwise.

import { answerLocally } from './local'
import { apiBaseUrl, streamChat } from './sse'
import type { AssistantAnswer, AssistantContext, ChatMessage } from './types'

export interface AskOptions {
  /** Previous turns, oldest first (sent to the backend; the local engine answers each question alone). */
  history?: ChatMessage[]
  signal?: AbortSignal
  onUpdate?: (answer: AssistantAnswer) => void
  /** Overrides VITE_API_URL (tests). `null` forces the local provider. */
  baseUrl?: string | null
  fetch?: typeof fetch
}

export const assistantProvider = (): 'api' | 'local' => (apiBaseUrl() ? 'api' : 'local')

export async function askAssistant(question: string, ctx: AssistantContext, opts: AskOptions = {}): Promise<AssistantAnswer> {
  const baseUrl = opts.baseUrl === undefined ? apiBaseUrl() : opts.baseUrl
  if (!baseUrl) return answerLocally(question, ctx)
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
