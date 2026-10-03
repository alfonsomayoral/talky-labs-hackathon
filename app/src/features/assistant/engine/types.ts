// Typed answers of the assistant. Both providers (local and API) produce the same shape, and the
// cards are plain JSON so the backend can send them as `event: card` (CONTRACT.md §2).

import type { DatasetCore, DatasetMeta, DerivedRun, ItemId, ItemStatus, Priority, RunBundle, TaskKey } from '@/domain/types'
import type { Override } from '@/features/attention/overridesStore'
import type { ReasoningFact, ReasoningStep } from '@/features/item/kit'

export type ChatMode = 'fast' | 'deep'

export type Intent =
  | { kind: 'summary' }
  | { kind: 'review' }
  | { kind: 'balance' }
  | { kind: 'cost' }
  | { kind: 'unknown' }
  | { kind: 'process'; task: TaskKey | null }
  | { kind: 'explain'; token: string }
  | { kind: 'bank'; account: string | null }

export type IntentKind = Intent['kind']

export type MetricValue =
  | { kind: 'number'; value: number }
  | { kind: 'percent'; value: number | null }
  | { kind: 'money'; cents: number | null; currency: string }
  | { kind: 'text'; text: string }

export interface MetricDatum {
  label: string
  value: MetricValue
  delta?: string
  comparison?: string
  hint?: string
}

export type TableCell =
  | { kind: 'text'; text: string }
  | { kind: 'mono'; text: string }
  | { kind: 'number'; value: number }
  | { kind: 'percent'; value: number | null }
  | { kind: 'money'; amounts: { cents: number; currency: string }[] }
  | { kind: 'item'; item: ItemId; label: string }

export interface TableColumn {
  label: string
  align?: 'left' | 'right'
}

export interface CardItem {
  item: ItemId
  title?: string
  amount?: number | null
  currency?: string | null
  priority?: Priority
  status?: ItemStatus
}

export type AssistantCard =
  | { type: 'metric'; title?: string; metrics: MetricDatum[] }
  | { type: 'table'; title?: string; columns: TableColumn[]; rows: TableCell[][] }
  | { type: 'items'; title?: string; items: CardItem[]; total?: number }
  | { type: 'reasoning'; item: ItemId; headline: string; facts: ReasoningFact[]; steps: ReasoningStep[] }
  | { type: 'process'; task: TaskKey }

export type Citation = { item: ItemId } | { policy_ref: string }

export interface AnswerLink {
  label: string
  to: string
}

export interface AssistantAnswer {
  text: string
  cards: AssistantCard[]
  citations: Citation[]
  links: AnswerLink[]
  intent: IntentKind | null
  source: 'local' | 'api'
}

/** Everything the local provider reads: the derived run, the dataset and the human overrides. */
export interface AssistantContext {
  data: DerivedRun
  core: DatasetCore
  meta: DatasetMeta
  run: RunBundle
  overrides: readonly Override[]
  mode: ChatMode
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}
