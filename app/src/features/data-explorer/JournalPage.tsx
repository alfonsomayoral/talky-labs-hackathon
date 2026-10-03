// `/datos/diario`: the journal (36.743 entries in July), queried in the worker page by page.
import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { Search } from 'lucide-react'
import { Amount, Button, DataTable, FilterBar, FilterChip, Mono, Page, PageHeader, type Column } from '@/components'
import type { DatasetApi, JournalEntry } from '@/domain/types'
import { formatDate, formatNumber } from '@/lib/format'
import { SectionTabs, useApi } from './common'
import { dataPath, journalFilters, journalParams, type JournalFilters } from './model'
import styles from './DataExplorer.module.css'

const PAGE = 500

interface JournalState {
  status: 'loading' | 'ready' | 'error'
  total: number
  entries: JournalEntry[]
  error: string | null
}

/** Pages of entries matching `filters`; `more()` appends the next page. */
export function useJournal(api: DatasetApi, filters: JournalFilters) {
  const key = JSON.stringify(filters)
  const [state, setState] = useState<JournalState & { key: string }>({ key, status: 'loading', total: 0, entries: [], error: null })
  const [loadingMore, setLoadingMore] = useState(false)

  useEffect(() => {
    let alive = true
    api.queryJournal({ ...(JSON.parse(key) as JournalFilters), limit: PAGE }).then(
      (r) => alive && setState({ key, status: 'ready', total: r.total, entries: r.entries, error: null }),
      (e: unknown) => alive && setState({ key, status: 'error', total: 0, entries: [], error: e instanceof Error ? e.message : String(e) }),
    )
    return () => {
      alive = false
    }
  }, [api, key])

  const more = () => {
    setLoadingMore(true)
    api
      .queryJournal({ ...filters, offset: state.entries.length, limit: PAGE })
      .then((r) => setState((s) => (s.key === key ? { ...s, entries: [...s.entries, ...r.entries] } : s)))
      .finally(() => setLoadingMore(false))
  }

  return { ...(state.key === key ? state : { status: 'loading' as const, total: 0, entries: [], error: null }), more, loadingMore }
}

const debit = (e: JournalEntry) => e.lines.reduce((s, l) => s + (l.debit || 0), 0)

export function useJournalColumns(withCompany = true): Column<JournalEntry>[] {
  return useMemo<Column<JournalEntry>[]>(
    () => [
      { id: 'id', header: 'Asiento', width: 160, cell: (e) => <Mono>{e.id}</Mono>, sortValue: (e) => e.id },
      { id: 'date', header: 'Fecha', width: 110, cell: (e) => formatDate(e.posting_date), sortValue: (e) => e.posting_date },
      ...(withCompany ? [{ id: 'company', header: 'Sociedad', width: 80, cell: (e: JournalEntry) => <Mono>{e.company}</Mono>, sortValue: (e: JournalEntry) => e.company }] : []),
      { id: 'source', header: 'Origen', width: 130, cell: (e) => <Mono>{e.source}</Mono>, sortValue: (e) => e.source },
      { id: 'reference', header: 'Referencia', width: 'minmax(130px, 1fr)', cell: (e) => (e.reference ? <Mono>{e.reference}</Mono> : null) },
      { id: 'text', header: 'Texto', width: 'minmax(200px, 2fr)', cell: (e) => e.header_text },
      { id: 'lines', header: 'Líneas', width: 64, align: 'right', cell: (e) => e.lines.length },
      { id: 'amount', header: 'Importe', width: 172, align: 'right', cell: (e) => <Amount cents={debit(e)} currency={e.currency} />, sortValue: debit },
    ],
    [withCompany],
  )
}

export function JournalPage() {
  const api = useApi()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const filters = useMemo(() => journalFilters(params), [params])
  const journal = useJournal(api, filters)
  const columns = useJournalColumns()
  const apply = (next: JournalFilters) => setParams(journalParams(next), { replace: true })
  const active = Object.keys(filters).length > 0

  const sources = useMemo(() => [...new Set(journal.entries.map((e) => e.source))].sort(), [journal.entries])
  const companies = api.core.companies.map((c) => ({ value: c.code, label: `${c.code} · ${c.short}` }))

  return (
    <Page fill>
      <PageHeader
        title="Datos"
        subtitle="Diario de todas las sociedades: filtra por sociedad, cuenta, origen, fechas o texto."
        filters={
          <div className={styles.headerStack}>
            <SectionTabs />
            <FilterBar
              onClear={active ? () => apply({}) : undefined}
              end={
                <span className={styles.count}>
                  {journal.status === 'ready' ? `${formatNumber(journal.entries.length)} de ${formatNumber(journal.total)} asientos` : 'Buscando…'}
                </span>
              }
            >
              <FilterChip
                label="Sociedad"
                options={companies}
                selected={filters.company ? [filters.company] : []}
                onChange={(next) => apply({ ...filters, company: next.find((c) => c !== filters.company) })}
              />
              <JournalForm key={JSON.stringify(filters)} filters={filters} sources={sources} onApply={apply} />
            </FilterBar>
          </div>
        }
      />
      <DataTable
        aria-label="Asientos del diario"
        rows={journal.entries}
        columns={columns}
        getRowId={(e) => e.id}
        onOpen={(e) => navigate(dataPath.entry(e.id))}
        globalKeys
        empty={journal.status === 'error' ? <p className={styles.error}>{journal.error}</p> : undefined}
      />
      {journal.status === 'ready' && journal.entries.length < journal.total && (
        <div className={styles.more}>
          <Button size="sm" onClick={journal.more} loading={journal.loadingMore}>
            Cargar {formatNumber(Math.min(PAGE, journal.total - journal.entries.length))} más
          </Button>
        </div>
      )}
    </Page>
  )
}

/** Free-text filters; applied on Enter or with the button so each keystroke does not query 36k entries. */
function JournalForm({ filters, sources, onApply }: { filters: JournalFilters; sources: string[]; onApply: (f: JournalFilters) => void }) {
  const [draft, setDraft] = useState(filters)
  const set = (k: keyof JournalFilters) => (e: { target: { value: string } }) => setDraft((d) => ({ ...d, [k]: e.target.value }))
  const submit = (e: FormEvent) => {
    e.preventDefault()
    onApply({ ...draft, company: filters.company })
  }
  return (
    <form className={styles.journalForm} onSubmit={submit} role="search">
      <input className={styles.input} aria-label="Cuenta" placeholder="Cuenta" value={draft.account ?? ''} onChange={set('account')} size={10} />
      <input className={styles.input} aria-label="Origen" placeholder="Origen" list="journal-sources" value={draft.source ?? ''} onChange={set('source')} size={10} />
      <datalist id="journal-sources">
        {sources.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
      <input className={styles.input} type="date" aria-label="Desde" value={draft.from ?? ''} onChange={set('from')} />
      <input className={styles.input} type="date" aria-label="Hasta" value={draft.to ?? ''} onChange={set('to')} />
      <input className={styles.input} type="search" aria-label="Texto" placeholder="Id, referencia, texto, socio…" value={draft.text ?? ''} onChange={set('text')} size={24} />
      <Button type="submit" size="sm" leadingIcon={<Search />}>
        Buscar
      </Button>
    </form>
  )
}
