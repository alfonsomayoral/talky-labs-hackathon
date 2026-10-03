// WorkItem ids (domain/types/workitem.ts): `<task>:<key>`.

import type { ItemId, TaskKey } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { get, pyCompare, pyIter } from './score/py'
import { closeKeyParts } from './score/tasks'

export const apItemId = (docId: unknown): ItemId => `ap:${String(docId)}`
export const arBillingItemId = (billingItem: unknown): ItemId => `ar_billing:${String(billingItem)}`
export const arCashItemId = (bankLine: unknown): ItemId => `ar_cash:${String(bankLine)}`
export const bankItemId = (account: unknown, key: string): ItemId => `bank_rec:${String(account)}/${key}`
/** Account-level entry used by the golden comparison (adjustments, account score). */
export const bankAccountItemId = (account: unknown): ItemId => `bank_rec:${String(account)}`

export function icItemId(pair: unknown, cause: unknown): ItemId {
  return `ic:${[...pyIter(pair)].sort(pyCompare).map(String).join('-')}/${String(cause)}`
}

export const closeItemId = (type: unknown, company: unknown, key: unknown): ItemId =>
  `close:${String(type)}/${String(company)}/${key === null || key === undefined ? '-' : String(key)}`

export function parseItemId(id: ItemId): { task: TaskKey; key: string } | null {
  const i = id.indexOf(':')
  const task = id.slice(0, i) as TaskKey
  return i > 0 && TASK_KEYS.includes(task) ? { task, key: id.slice(i + 1) } : null
}

export interface BankRowKeys {
  matches: string[]
  unmatchedBank: string[]
  unmatchedBook: string[]
}

/**
 * Item keys inside one bank_rec row: a match takes its first bank line (as the backend's
 * events do) or `match-<n>`; unmatched lines take their own id. Collisions get a suffix.
 */
export function bankRowKeys(row: unknown): BankRowKeys {
  const used = new Set<string>()
  const claim = (preferred: string | null, fallback: string): string => {
    let key = preferred && !used.has(preferred) ? preferred : fallback
    for (let n = 2; used.has(key); n++) key = `${fallback}~${n}`
    used.add(key)
    return key
  }
  const firstBank = (m: unknown): string | null => {
    const b = pyIter(get(m, 'bank_lines'))[0]
    return b === undefined || b === null ? null : String(b)
  }
  return {
    matches: pyIter(get(row, 'matches')).map((m, i) => claim(firstBank(m), `match-${i + 1}`)),
    unmatchedBank: pyIter(get(row, 'unmatched_bank')).map((x, i) => claim(String(get(x, 'bank_line')), `bank-${i + 1}`)),
    unmatchedBook: pyIter(get(row, 'unmatched_book')).map((x, i) => claim(String(get(x, 'book_line')), `book-${i + 1}`)),
  }
}

const KEY_FIELDS = { ap: 'doc_id', ar_billing: 'billing_item', ar_cash: 'bank_line', bank_rec: 'account' } as const

/** Key of a deliverable row: its id field, the sorted ic pair + cause, or the close key. */
export function rowKey(task: TaskKey, row: unknown): string {
  if (task === 'ic') return icItemId(get(row, 'pair'), get(row, 'cause')).slice('ic:'.length)
  if (task === 'close') return closeItemId(...closeKeyParts(row)).slice('close:'.length)
  return String(get(row, KEY_FIELDS[task]))
}
