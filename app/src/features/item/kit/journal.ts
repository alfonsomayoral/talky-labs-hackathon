// Totals and balance check of a journal entry (lines may carry their own company).

import type { JeLine } from '@/domain/types'

export interface JournalTotals {
  debit: number
  credit: number
  /** Σdebit − Σcredit per company, only the companies that do not balance. */
  imbalance: Map<string, number>
  balanced: boolean
  /** Companies present in the lines (in order of appearance). */
  companies: string[]
}

const cents = (x: unknown): number => (typeof x === 'number' && Number.isFinite(x) ? x : 0)

export function journalTotals(lines: readonly JeLine[], defaultCompany: string | null = null): JournalTotals {
  let debit = 0
  let credit = 0
  const by = new Map<string, number>()
  for (const l of lines) {
    const d = cents(l.debit)
    const c = cents(l.credit)
    debit += d
    credit += c
    const company = String(l.company ?? defaultCompany ?? '')
    by.set(company, (by.get(company) ?? 0) + d - c)
  }
  const companies = [...by.keys()]
  const imbalance = new Map([...by].filter(([, v]) => v !== 0))
  return { debit, credit, imbalance, balanced: imbalance.size === 0, companies }
}
