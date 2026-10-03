import type { EvidenceRef, WorkItem } from '@/domain/types'
import { useDatasetStore } from '@/data/stores'
import { findStatementLine, parseBookLine } from './evidence'
import { bankMatchDetail, matchShape, type BookLineAmount } from './reasoning'
import { useAsync } from './useAsync'
import styles from './ReasoningView.module.css'

/** «Casada N:1 con 3 apuntes del libro, mismo día, importe exacto» — reads the book lines from the journal. */
export function BankMatchFacts({ item }: { item: WorkItem }) {
  const api = useDatasetStore((s) => s.api)
  const bankIds = item.evidence.filter((e): e is Extract<EvidenceRef, { kind: 'bank' }> => e.kind === 'bank').map((e) => e.bank_line)
  const bookIds = item.evidence.filter((e): e is Extract<EvidenceRef, { kind: 'journal' }> => e.kind === 'journal').map((e) => e.book_line)
  const key = `${bankIds.join(',')}|${bookIds.join(',')}`
  const state = useAsync(async () => {
    if (!api) return null
    const parsed = bookIds.map(parseBookLine)
    const entries = await api.getJournalEntries([...new Set(parsed.map((p) => p.entryId))])
    const byId = new Map(entries.map((e) => [e.id, e]))
    const books: BookLineAmount[] = []
    parsed.forEach((p, i) => {
      const e = byId.get(p.entryId)
      const line = e?.lines.find((l) => l.line === p.line) ?? (p.line !== null ? e?.lines[p.line - 1] : undefined)
      if (e && line) books.push({ id: bookIds[i], date: e.posting_date, amount: line.debit - line.credit })
    })
    const bank = bankIds.map((b) => findStatementLine(api.core, b)?.line).filter((l): l is NonNullable<typeof l> => !!l)
    if (books.length !== bookIds.length || bank.length !== bankIds.length) return null
    return bankMatchDetail(bank, books, bank[0]?.currency ?? 'EUR')
  }, [api, key])
  if (state.status !== 'ready' || !state.data) return null
  return (
    <p className={styles.matchDetail}>
      Casación {matchShape(bankIds.length, bookIds.length)}: {state.data}.
    </p>
  )
}
