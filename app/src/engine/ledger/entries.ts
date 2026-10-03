// Journal entries carried by each deliverable row, collected exactly like score.py's score_tb.

import type { Deliverables, JeLine, JournalEntryOut, TaskKey } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { get, getOr, isDict, pyIter, truthy } from '../score/py'

/** An entry as score_tb sees it: the row's company (fallback for lines) and the raw entry (object or list of lines). */
export interface RowEntry {
  company: unknown
  je: unknown
}

export function rowEntries(task: TaskKey, row: unknown): RowEntry[] {
  const company = get(row, 'company')
  const out: RowEntry[] = []
  if ((task === 'ap' || task === 'ar_billing' || task === 'close') && truthy(get(row, 'journal_entry'))) {
    out.push({ company, je: get(row, 'journal_entry') })
  }
  if ((task === 'ar_cash' || task === 'ic') && truthy(get(row, 'adjustment'))) out.push({ company, je: get(row, 'adjustment') })
  if (task === 'bank_rec') {
    for (const a of pyIter(getOr(row, 'adjustments', []))) out.push({ company, je: getOr(a, 'lines', []) })
  }
  return out
}

/** Deliverables with absent files treated as empty (score.py loads a missing file as []). */
export function effectiveDeliverables(run: {
  deliverables: Deliverables
  present?: Partial<Record<TaskKey, boolean>> | null
}): Deliverables {
  const out = {} as Record<TaskKey, unknown[]>
  for (const k of TASK_KEYS) out[k] = run.present?.[k] === false ? [] : (run.deliverables[k] ?? [])
  return out as unknown as Deliverables
}

/** Normalises a raw entry into `{company, lines}` for display (list entries take the row company; non-object lines are dropped). */
export function asJournalEntry(e: RowEntry): JournalEntryOut {
  const je = e.je
  const raw = Array.isArray(je) ? je : get(je, 'lines')
  const lines = (Array.isArray(raw) ? raw : []).filter(isDict) as JeLine[]
  if (Array.isArray(je)) return { company: String(e.company ?? lines[0]?.company ?? ''), lines }
  return { ...(je as JournalEntryOut), company: String(get(je, 'company') ?? e.company ?? ''), lines }
}

/** Σdebit of an entry (what a WorkItem reports as tbImpact). */
export function entryDebit(e: JournalEntryOut): number {
  let s = 0
  for (const l of e.lines) if (typeof l.debit === 'number') s += l.debit
  return s
}

/** Σdebit − Σcredit per company of the entry's lines; empty when balanced. */
export function entryImbalance(e: JournalEntryOut): Map<string, number> {
  const by = new Map<string, number>()
  for (const l of e.lines) {
    const c = String(l.company ?? e.company ?? '')
    const d = (Number(l.debit) || 0) - (Number(l.credit) || 0)
    by.set(c, (by.get(c) ?? 0) + d)
  }
  for (const [c, v] of by) if (v === 0) by.delete(c)
  return by
}
