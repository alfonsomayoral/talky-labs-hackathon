// score.py `main`: per-task scores rounded to 4 decimals and the weighted total (0–100).

import type { Deliverables, Golden, ScoreReport, TaskKey, TaskScore } from '@/domain/types'
import { TASK_KEYS, TASK_WEIGHTS } from '@/domain/types'
import { effectiveDeliverables } from '../ledger/entries'
import { diffItems } from './itemDiff'
import { fsum, pyRound } from './py'
import { scoreAp, scoreArBilling, scoreArCash, scoreBank, scoreClose, scoreIc, scoreTb, type Rows, type TaskResult } from './tasks'

const SCORERS: Record<TaskKey, (gold: Rows, sub: Rows) => TaskResult> = {
  ap: scoreAp,
  ar_billing: scoreArBilling,
  ar_cash: scoreArCash,
  bank_rec: scoreBank,
  ic: scoreIc,
  close: scoreClose,
}

const WEIGHT_ORDER = [...TASK_KEYS, 'trial_balance'] as const

/** Task scores and total exactly as score.py computes them (no per-item detail). */
export function scoreTotals(sub: Deliverables, golden: Golden): Pick<ScoreReport, 'total' | 'tasks'> {
  const tasks = {} as Record<TaskKey | 'trial_balance', TaskScore>
  for (const k of TASK_KEYS) {
    const r = SCORERS[k](golden.deliverables[k] ?? [], sub[k] ?? [])
    tasks[k] = { score: pyRound(r.score, 4), details: r.details }
  }
  const tb = scoreTb(golden.trialBalanceTruth ?? [], golden.trialBalanceRecorded ?? [], sub)
  tasks.trial_balance = { score: pyRound(tb.score, 4), details: tb.details }
  const total = pyRound(fsum(WEIGHT_ORDER.map((k) => TASK_WEIGHTS[k] * tasks[k].score)) * 100, 2)
  return { total, tasks }
}

/**
 * Scores a run against golden like `python score.py`: files flagged absent in
 * `present` count as missing (empty). Adds the per-item comparison.
 */
export function scoreRun(run: { deliverables: Deliverables; present?: Partial<Record<TaskKey, boolean>> }, golden: Golden): ScoreReport {
  const sub = effectiveDeliverables(run)
  return { ...scoreTotals(sub, golden), perItem: diffItems(golden.deliverables, sub) }
}
