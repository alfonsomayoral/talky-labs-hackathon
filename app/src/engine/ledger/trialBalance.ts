// Trial balance: recorded (journal) + every delivered entry = after, compared with the truth (golden).

import type { Cents, Deliverables, TaskKey, TbRow, TrialBalanceComparison, TrialBalanceRow } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { jeLines } from '../score/primitives'
import { tbKey } from '../score/tasks'
import { rowEntries } from './entries'

/**
 * Same arithmetic as score.py's score_tb: lines without a company (no line, row or
 * entry company) keep a null company and still count in the gaps.
 */
export function compareTrialBalance(
  recorded: readonly TrialBalanceRow[],
  deliverables: Deliverables,
  truth: readonly TrialBalanceRow[] | null,
): TrialBalanceComparison {
  const rows = new Map<string, TbRow>()
  const row = (company: unknown, account: string): TbRow => {
    const k = tbKey(company, account)
    let r = rows.get(k)
    if (!r) {
      r = { company: (company ?? '') as string, account, recorded: 0, delta: {}, after: 0, truth: truth ? 0 : null }
      rows.set(k, r)
    }
    return r
  }
  for (const r of recorded) {
    const x = row(r.company, r.account)
    x.recorded = r.balance
    x.after = r.balance
  }
  const movementByTask = Object.fromEntries(TASK_KEYS.map((k) => [k, 0])) as Record<TaskKey, Cents>
  for (const task of TASK_KEYS) {
    for (const r of deliverables[task] ?? []) {
      for (const e of rowEntries(task, r)) {
        for (const l of jeLines(e.je, e.company)) {
          const x = row(l.company, l.account)
          x.delta[task] = (x.delta[task] ?? 0) + l.amount
          x.after += l.amount
        }
      }
    }
  }
  for (const x of rows.values()) for (const task of TASK_KEYS) movementByTask[task] += Math.abs(x.delta[task] ?? 0)
  if (truth) for (const r of truth) row(r.company, r.account).truth = r.balance

  const list = [...rows.values()].sort((a, b) => (a.company === b.company ? cmp(a.account, b.account) : cmp(a.company, b.company)))
  if (!truth) return { rows: list, gapRecorded: null, gapAfter: null, score: null, movementByTask }
  let gapRecorded = 0
  let gapAfter = 0
  for (const x of list) {
    gapRecorded += Math.abs((x.truth ?? 0) - x.recorded)
    gapAfter += Math.abs((x.truth ?? 0) - x.after)
  }
  return { rows: list, gapRecorded, gapAfter, score: Math.max(0, 1 - gapAfter / (gapRecorded || 1)), movementByTask }
}

const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0)
