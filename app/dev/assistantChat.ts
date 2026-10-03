// Dev-only Vite middleware for the Assistant's «Profundo» mode: POST /api/chat (CONTRACT.md §2)
// answered by an OpenAI model. The key stays on this server (app/.env.local, never VITE_-prefixed)
// and never reaches the browser. The browser sends its local answer as `context`: the model only
// writes the text over those figures, so they cannot drift from Resumen and Atención.
import type { IncomingMessage, ServerResponse } from 'node:http'
import type { Plugin } from 'vite'

export interface AssistantChatOptions {
  apiKey?: string
  projectId?: string
  model?: string
}

type Next = (err?: unknown) => void
type Message = { role: 'user' | 'assistant'; content: string }

const DEFAULT_MODEL = 'gpt-6-luna'
const OPENAI_URL = 'https://api.openai.com/v1/responses'

const INSTRUCTIONS = `Eres el Asistente de Kalmora Close, el puesto de mando del cierre mensual de Grupo Kalmora.
Responde directamente a la última pregunta, en español y en texto plano: de 2 a 5 frases, sin Markdown ni listas.
Usa solo las cifras, partidas y artículos de la política que vienen en CONTEXTO; no calcules ni inventes otros.
Las tablas y tarjetas del contexto ya se ven en pantalla: no las copies; di qué significan y por dónde empezar, citando como mucho tres partidas.
Si el contexto no responde la pregunta, dilo en una frase.`

function readBody(req: IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    let body = ''
    req.on('data', (c: Buffer) => (body += c.toString('utf8')))
    req.on('end', () => resolve(body))
    req.on('error', reject)
  })
}

const sse = (res: ServerResponse, event: string, data: unknown) => res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`)

/** Deltas of an OpenAI Responses stream (`response.output_text.delta`), in order. */
export async function* responseDeltas(body: ReadableStream<Uint8Array>): AsyncGenerator<string> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let cut: number
    while ((cut = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, cut)
      buffer = buffer.slice(cut + 2)
      const data = block
        .split('\n')
        .filter((l) => l.startsWith('data:'))
        .map((l) => l.slice(5).trim())
        .join('\n')
      if (!data || data === '[DONE]') continue
      const msg = JSON.parse(data) as { type?: string; delta?: string; error?: { message?: string }; response?: { error?: { message?: string } } }
      if (msg.type === 'response.output_text.delta' && msg.delta) yield msg.delta
      else if (msg.type === 'error' || msg.type === 'response.failed') throw new Error(msg.error?.message ?? msg.response?.error?.message ?? 'El modelo no pudo responder')
    }
  }
}

export function createAssistantChatHandler(options: AssistantChatOptions, doFetch: typeof fetch = fetch) {
  const model = options.model || DEFAULT_MODEL
  return async (req: IncomingMessage, res: ServerResponse, next: Next) => {
    const url = req.url ?? ''
    if (url === '/api/chat/status' && req.method === 'GET') {
      res.setHeader('Content-Type', 'application/json')
      return res.end(JSON.stringify({ enabled: !!options.apiKey, model }))
    }
    if (url !== '/api/chat' || req.method !== 'POST') return next()
    if (!options.apiKey) {
      res.statusCode = 503
      return res.end('OPENAI_API_KEY no está definida en app/.env.local')
    }
    res.writeHead(200, { 'Content-Type': 'text/event-stream; charset=utf-8', 'Cache-Control': 'no-cache', Connection: 'keep-alive' })
    try {
      const { messages = [], context = null } = JSON.parse(await readBody(req)) as { messages?: Message[]; context?: unknown }
      const input = [
        ...messages.slice(0, -1).map((m) => ({ role: m.role, content: m.content })),
        { role: 'user' as const, content: `CONTEXTO (calculado por la app sobre la ejecución activa):\n${JSON.stringify(context)}\n\nPREGUNTA: ${messages.at(-1)?.content ?? ''}` },
      ]
      const upstream = await doFetch(OPENAI_URL, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${options.apiKey}`,
          'Content-Type': 'application/json',
          ...(options.projectId ? { 'OpenAI-Project': options.projectId } : {}),
        },
        body: JSON.stringify({ model, instructions: INSTRUCTIONS, input, stream: true, max_output_tokens: 1200 }),
      })
      if (!upstream.ok || !upstream.body) throw new Error(`OpenAI respondió ${upstream.status}`)
      for await (const text of responseDeltas(upstream.body)) sse(res, 'delta', { text })
      sse(res, 'done', {})
    } catch (e) {
      sse(res, 'error', { text: e instanceof Error ? e.message : String(e) })
    }
    res.end()
  }
}

export function assistantChat(options: AssistantChatOptions): Plugin {
  return {
    name: 'kalmora-assistant-chat',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use((req, res, next) => void createAssistantChatHandler(options)(req, res, next))
    },
  }
}
