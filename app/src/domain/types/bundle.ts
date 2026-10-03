// Run bundle produced by the backend (CONTRACT.md). Only `deliverables` is required.

import type { Cents } from './erp'
import type { Deliverables, TaskKey } from './deliverables'

export interface ModelUsage {
  provider: string
  name: string
  calls: number
  input_tokens: number
  output_tokens: number
  cost_usd: number
}

export interface RunManifest {
  run_id: string
  dataset?: string
  month?: string
  started_at?: string
  finished_at?: string
  runtime_s?: number
  models?: ModelUsage[]
  cost_usd_total?: number
  agent_version?: string
  policies_sha256?: string
  tasks?: Partial<Record<TaskKey, { started_at?: string; finished_at?: string }>>
  human_overrides?: number
  [k: string]: unknown
}

export type EventKind = 'EXTRACT' | 'CHECK' | 'MATCH' | 'CLASSIFY' | 'ESTIMATE' | 'DECIDE' | 'POST' | 'MODEL_CALL' | 'HUMAN_OVERRIDE'
export type EventResult = 'PASS' | 'FAIL' | 'INFO'

export type EvidenceRef =
  | { kind: 'doc'; path: string; locator?: string }
  | { kind: 'erp'; file: string; key: string; field?: string }
  | { kind: 'bank'; account: string; bank_line: string }
  | { kind: 'journal'; book_line: string }
  | { kind: 'precedent'; text: string }

export interface ModelCall {
  provider: string
  name: string
  question?: string
  answer?: string
  probabilities?: Record<string, number>
  input_tokens?: number
  output_tokens?: number
  cost_usd?: number
}

/** `trace/events.jsonl` — `item` is the WorkItem id (`<task>:<key>`). */
export interface AgentEvent {
  event_id: string
  item: string
  seq: number
  ts: string
  kind: EventKind
  step: string
  result: EventResult
  policy_ref?: string | null
  summary: string
  evidence?: EvidenceRef[]
  model?: ModelCall | null
  confidence?: number | null
  duration_ms?: number
}

export const ATTENTION_KINDS = [
  'FRAUD_SIGNAL',
  'MATERIAL_UNEXPLAINED',
  'AGENT_DOUBT',
  'ESTIMATE',
  'CROSS_TASK',
  'POLICY_EXCEPTION',
  'MASTER_DATA',
  'DATA_QUALITY',
] as const
export type AttentionKind = (typeof ATTENTION_KINDS)[number]
export type Priority = 'P0' | 'P1' | 'P2' | 'P3'

/** `trace/attention.jsonl` or derived by the engine. */
export interface AttentionItem {
  attention_id: string
  item: string
  kind: AttentionKind
  priority: Priority
  title: string
  impact: Cents
  affects_tb: boolean
  policy_ref?: string | null
  recommendation?: { decision?: string; reasons?: string[]; [k: string]: unknown } | null
  alternatives?: { decision: string; p: number }[]
  suggested_action?: string
  /** Probability that the agent's decision is right, when known. */
  confidence?: number | null
  /** true when produced by the app's heuristics instead of the backend. */
  derived?: boolean
}

export type RunSource = 'golden' | 'import' | 'api'

export interface RunBundle {
  id: string
  datasetId: string
  source: RunSource
  label: string
  createdAt: string
  manifest: RunManifest | null
  deliverables: Deliverables
  /** Which deliverable files were present (absent ones score 0). */
  present: Record<TaskKey, boolean>
  events: AgentEvent[] | null
  attention: AttentionItem[] | null
}
