// Everything the views read for a dataset + run (DerivedRun).

import type { DatasetCore, DerivedRun, RunBundle, TrialBalanceRow } from '@/domain/types'
import { compareTrialBalance } from '../ledger/trialBalance'
import { effectiveDeliverables } from '../ledger/entries'
import { scoreRun } from '../score/score'
import { validateDeliverables } from '../validate/validate'
import { applyAttentionStatus, deriveAttention } from './attention'
import { synthesizeEvents } from './events'
import { buildItems, groupEvents } from './items'
import { computeStats } from './stats'
import { makeToEur } from '../fx'

/** Derives items, attention, trace, validation, score (with golden) and trial balance (with `recorded`). */
export function deriveRun(core: DatasetCore, run: RunBundle, recorded: readonly TrialBalanceRow[] | null): DerivedRun {
  const base = buildItems(core, run).items
  const attention = run.attention ?? deriveAttention(core, run, base)
  const items = applyAttentionStatus(base, attention)
  const eventsSynthesized = run.events === null || run.events === undefined
  const events = eventsSynthesized ? synthesizeEvents(core, run, items) : run.events!
  const validation = validateDeliverables(core, run)
  const derived: DerivedRun = {
    runId: run.id,
    items,
    itemsById: new Map(items.map((it) => [it.id, it])),
    attention,
    events,
    eventsByItem: groupEvents(events),
    eventsSynthesized,
    validation,
    trialBalance: null,
    score: core.golden ? scoreRun(run, core.golden) : null,
    stats: computeStats(items, attention, validation, makeToEur(core)),
  }
  return recorded ? withTrialBalance(derived, core, run, recorded) : derived
}

/** Adds the trial balance comparison once the recorded balance (from the journal) is known. */
export function withTrialBalance(derived: DerivedRun, core: DatasetCore, run: RunBundle, recorded: readonly TrialBalanceRow[]): DerivedRun {
  return { ...derived, trialBalance: compareTrialBalance(recorded, effectiveDeliverables(run), core.golden?.trialBalanceTruth ?? null, makeToEur(core)) }
}
