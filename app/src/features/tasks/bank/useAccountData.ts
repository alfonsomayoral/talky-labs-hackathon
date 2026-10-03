// Async inputs of one account view: its GL lines (history to month end).
import { useEffect, useState } from 'react'
import type { BankAccount, BankRecRow, DatasetApi, JournalEntry } from '@/domain/types'
import { bookLinesOf, entryIdOf, referencedBookLines, type BookLine } from './model'

export interface AccountData {
  status: 'loading' | 'ready' | 'error'
  error: string | null
  /** GL lines posted in the closing month. */
  monthBook: BookLine[]
  /** Lines the deliverable mentions that fall outside the month. */
  referencedBook: BookLine[]
  glClosing: number
  glMovement: number
}

const PAGE = 5000

async function allEntries(api: DatasetApi, account: BankAccount, to: string): Promise<JournalEntry[]> {
  const out: JournalEntry[] = []
  for (let offset = 0; ; offset += PAGE) {
    const page = await api.queryJournal({ company: account.company, account: account.gl_account, to, offset, limit: PAGE })
    out.push(...page.entries)
    if (!page.entries.length || out.length >= page.total) return out
  }
}

export function monthBounds(month: string): { from: string; to: string } {
  const [y, m] = month.split('-').map(Number)
  const last = new Date(Date.UTC(y, m, 0)).getUTCDate()
  return { from: `${month}-01`, to: `${month}-${String(last).padStart(2, '0')}` }
}

const LOADING: AccountData = { status: 'loading', error: null, monthBook: [], referencedBook: [], glClosing: 0, glMovement: 0 }

export function useAccountData(api: DatasetApi, account: BankAccount, row: BankRecRow | null): AccountData {
  const key = `${api.meta.id}|${account.id}|${row ? 'row' : '-'}`
  const [state, setState] = useState<{ key: string; data: AccountData } | null>(null)

  useEffect(() => {
    let alive = true
    const { from, to } = monthBounds(api.meta.month)
    const companyCurrency = api.core.companies.find((c) => c.code === account.company)?.currency ?? account.currency
    const load = async (): Promise<AccountData> => {
      const entries = await allEntries(api, account, to)
      const all = bookLinesOf(entries, account, companyCurrency)
      const monthBook = all.filter((l) => l.date >= from)
      const known = new Set(all.map((l) => l.id))
      const missing = row ? referencedBookLines(row).filter((id) => !known.has(id)) : []
      const extra = missing.length ? bookLinesOf(await api.getJournalEntries([...new Set(missing.map(entryIdOf))]), account, companyCurrency) : []
      return {
        status: 'ready',
        error: null,
        monthBook,
        referencedBook: [...all.filter((l) => l.date < from), ...extra],
        glClosing: all.reduce((s, l) => s + l.amount, 0),
        glMovement: monthBook.reduce((s, l) => s + l.amount, 0),
      }
    }
    load().then(
      (data) => alive && setState({ key, data }),
      (e: unknown) => alive && setState({ key, data: { ...LOADING, status: 'error', error: e instanceof Error ? e.message : String(e) } }),
    )
    return () => {
      alive = false
    }
  }, [api, account, row, key])

  return state?.key === key ? state.data : LOADING
}
