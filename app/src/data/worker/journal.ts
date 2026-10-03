// Compact in-worker journal: the raw JSONL bytes plus per-entry columns and indexes.
// Entries are decoded from their byte range only when a query returns them.
import type { JournalEntry, JournalQuery, TrialBalanceRow } from '@/domain/types'

export interface JournalIndex {
  size: number
  bytes: Uint8Array
  starts: Uint32Array
  ends: Uint32Array
  ids: string[]
  company: string[]
  date: string[]
  source: string[]
  /** Lower-case id, reference, header text, partners and assignments. */
  search: string[]
  byId: Map<string, number>
  byAccount: Map<string, number[]>
  months: string[]
  trialBalance: TrialBalanceRow[]
}

export const DEFAULT_LIMIT = 100

export function buildJournalIndex(bytes: Uint8Array, onProgress?: (done: number, total: number) => void): JournalIndex {
  const decoder = new TextDecoder()
  const starts: number[] = []
  const ends: number[] = []
  const ids: string[] = []
  const company: string[] = []
  const date: string[] = []
  const source: string[] = []
  const search: string[] = []
  const byId = new Map<string, number>()
  const byAccount = new Map<string, number[]>()
  const intern = new Map<string, string>()
  const keep = (s: string) => intern.get(s) ?? (intern.set(s, s), s)
  const tb = new Map<string, Map<string, number>>()
  const months = new Set<string>()

  let pos = 0
  let nextReport = 0
  while (pos < bytes.length) {
    let nl = bytes.indexOf(10, pos)
    if (nl === -1) nl = bytes.length
    let end = nl
    if (end > pos && bytes[end - 1] === 13) end--
    if (end > pos) {
      const text = decoder.decode(bytes.subarray(pos, end))
      if (text.trim()) {
        let e: JournalEntry
        try {
          e = JSON.parse(text) as JournalEntry
        } catch (err) {
          throw new Error(`erp/journal_entries.jsonl, asiento ${ids.length + 1}: ${err instanceof Error ? err.message : String(err)}`)
        }
        const i = ids.length
        starts.push(pos)
        ends.push(end)
        ids.push(e.id)
        byId.set(e.id, i)
        company.push(keep(e.company))
        date.push(keep(e.posting_date))
        source.push(keep(e.source))
        months.add(e.posting_date.slice(0, 7))
        const words = [e.id, e.reference, e.header_text]
        let balances = tb.get(e.company)
        if (!balances) tb.set(e.company, (balances = new Map()))
        for (const l of e.lines) {
          const list = byAccount.get(l.account)
          if (!list) byAccount.set(l.account, [i])
          else if (list[list.length - 1] !== i) list.push(i)
          balances.set(l.account, (balances.get(l.account) ?? 0) + (l.debit || 0) - (l.credit || 0))
          if (l.partner) words.push(l.partner)
          if (l.assignment) words.push(l.assignment)
        }
        search.push(words.join(' ').toLowerCase())
      }
    }
    pos = nl + 1
    if (onProgress && pos >= nextReport) {
      onProgress(Math.min(pos, bytes.length), bytes.length)
      nextReport = pos + 4_000_000
    }
  }

  const trialBalance: TrialBalanceRow[] = []
  for (const c of [...tb.keys()].sort())
    for (const [account, balance] of [...tb.get(c)!].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
      if (balance !== 0) trialBalance.push({ company: c, account, balance })

  return {
    size: ids.length,
    bytes,
    starts: Uint32Array.from(starts),
    ends: Uint32Array.from(ends),
    ids,
    company,
    date,
    source,
    search,
    byId,
    byAccount,
    months: [...months].sort(),
    trialBalance,
  }
}

const decoder = new TextDecoder()

export function entryAt(idx: JournalIndex, i: number): JournalEntry {
  return JSON.parse(decoder.decode(idx.bytes.subarray(idx.starts[i], idx.ends[i]))) as JournalEntry
}

const fromDate = (d: string) => (d.length === 7 ? `${d}-01` : d)
const toDate = (d: string) => (d.length === 7 ? `${d}-31` : d)

export function queryJournalIndex(idx: JournalIndex, q: JournalQuery): { total: number; entries: JournalEntry[] } {
  if (q.account && q.accountPrefix && !q.account.startsWith(q.accountPrefix)) return { total: 0, entries: [] }
  let candidates: number[] | null = null
  if (q.ids?.length) {
    const seen = new Set<number>()
    candidates = []
    for (const id of q.ids) {
      const i = idx.byId.get(id.split('#')[0])
      if (i !== undefined && !seen.has(i)) {
        seen.add(i)
        candidates.push(i)
      }
    }
  } else if (q.account) candidates = idx.byAccount.get(q.account) ?? []
  else if (q.accountPrefix) {
    const set = new Set<number>()
    for (const [acc, list] of idx.byAccount) if (acc.startsWith(q.accountPrefix)) for (const i of list) set.add(i)
    candidates = [...set].sort((a, b) => a - b)
  }

  const from = q.from ? fromDate(q.from) : null
  const to = q.to ? toDate(q.to) : null
  const text = q.text?.trim().toLowerCase() || null
  const match = (i: number) =>
    (!q.company || idx.company[i] === q.company) &&
    (!q.source || idx.source[i] === q.source) &&
    (!from || idx.date[i] >= from) &&
    (!to || idx.date[i] <= to) &&
    (!text || idx.search[i].includes(text))

  const offset = Math.max(0, q.offset ?? 0)
  const limit = Math.max(0, q.limit ?? DEFAULT_LIMIT)
  const page: number[] = []
  let total = 0
  const visit = (i: number) => {
    if (!match(i)) return
    if (total >= offset && page.length < limit) page.push(i)
    total++
  }
  if (candidates) candidates.forEach(visit)
  else for (let i = 0; i < idx.size; i++) visit(i)
  return { total, entries: page.map((i) => entryAt(idx, i)) }
}

/** Entries by id; `<id>#<line>` book line ids are accepted. Unknown ids are skipped. */
export function journalEntriesById(idx: JournalIndex, ids: string[]): JournalEntry[] {
  return queryJournalIndex(idx, { ids, limit: ids.length }).entries
}
