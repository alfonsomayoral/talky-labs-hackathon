// Answer engine of the assistant (PLAN.md Fase 6.B).
export * from './types'
export { detectIntent, normalize } from './intent'
export { answerLocally, findItem, PRESET_QUESTIONS } from './local'
export { apiBaseUrl, normalizeCard, normalizeCitation, readSse, streamChat, type ChatRequest, type SseMessage, type StreamOptions } from './sse'
export { askAssistant, assistantProvider, type AskOptions } from './provider'
