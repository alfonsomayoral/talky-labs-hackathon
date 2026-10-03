// What the engine derives from a dataset + a run. Views only read this.

import type { CompanyCode, Cents } from './erp'
import type { TaskKey } from './deliverables'
import type { AgentEvent, AttentionItem } from './bundle'
import type { ItemId, WorkItem } from './workitem'

export interface FileValidation {
  task: TaskKey
  present: boolean
  rows: number
  /** Items listed in tasks/ for this deliverable (bank_rec: accounts; ic/close: not fixed). */
  expected: number | null
  missingKeys: string[]
  duplicateKeys: string[]
  extraKeys: string[]
  /** Entries whose Σdebit ≠ Σcredit (key of the row). */
  unbalancedEntries: string[]
  nonIntegerAmounts: number
  unknownAccounts: string[]
  invalidValues: { key: string; field: string; value: unknown }[]
  errors: string[]
  warnings: string[]
}

export interface ValidationReport {
  ok: boolean
  files: Record<TaskKey, FileValidation>
}

export interface FieldDiff {
  /** e.g. `decision`, `header.net`, `journal_entry.lines`, `matches`. */
  path: string
  expected: unknown
  actual: unknown
}

export interface ItemScore {
  item: ItemId
  /** 0..1 contribution of this item as the scorer sees it (when meaningful). */
  score: number | null
  exact: boolean
  diffs: FieldDiff[]
}

export interface TaskScore {
  score: number
  /** Same keys as score.py's details (decision_macro_f1, header, coding, per_account, …). */
  details: Record<string, unknown>
}

export interface ScoreReport {
  /** 0..100, as score.py `total`. */
  total: number
  tasks: Record<TaskKey | 'trial_balance', TaskScore>
  perItem: Record<ItemId, ItemScore>
}

export interface TbRow {
  company: CompanyCode
  account: string
  recorded: Cents
  delta: Partial<Record<TaskKey, Cents>>
  after: Cents
  truth: Cents | null
}

export interface TrialBalanceComparison {
  rows: TbRow[]
  /** Σ|truth − recorded| (null without golden). */
  gapRecorded: Cents | null
  /** Σ|truth − after| (null without golden). */
  gapAfter: Cents | null
  /** 1 − gapAfter / gapRecorded, as score.py (null without golden). */
  score: number | null
  /** Σ|delta| per task — how much each task moves the ledger. */
  movementByTask: Record<TaskKey, Cents>
  /** Same figures converted to EUR at the month-end SYN-BCE rate (the scorer mixes local currencies). */
  eur?: { gapRecorded: Cents | null; gapAfter: Cents | null; movementByTask: Record<TaskKey, Cents> }
}

export interface RunStats {
  items: number
  byStatus: Record<string, number>
  byTask: Record<TaskKey, { items: number; auto: number; needsHuman: number; blocked: number; open: number }>
  /** `impact` sums local-currency cents (as the scorer would); `impactEur` converts each item to EUR. */
  attention: { count: number; impact: Cents; impactEur?: Cents; byPriority: Record<string, number> }
  unbalancedEntries: number
}

export interface DerivedRun {
  runId: string
  items: WorkItem[]
  itemsById: Map<ItemId, WorkItem>
  attention: AttentionItem[]
  /** Backend events when present; otherwise a minimal trace synthesized from the deliverables. */
  events: AgentEvent[]
  eventsByItem: Map<ItemId, AgentEvent[]>
  eventsSynthesized: boolean
  validation: ValidationReport
  /** Null until the recorded trial balance (from the journal) has been computed. */
  trialBalance: TrialBalanceComparison | null
  /** Null when the dataset has no golden/. */
  score: ScoreReport | null
  stats: RunStats
}
