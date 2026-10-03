// `/tareas/ap` Bandeja de proveedores: ¿qué se hizo con cada documento?
import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { Search } from 'lucide-react'
import { Amount, Badge, DataTable, FilterBar, FilterChip, Mono, Page, PageHeader, QueryState, Section, type Column } from '@/components'
import type { ApRow, DatasetApi, DerivedRun, RunBundle } from '@/domain/types'
import { AP_DECISION_CATALOG, AP_DOCUMENT_TYPE_CATALOG, AP_REASON_CATALOG } from '@/domain/catalog/policy'
import { useDatasetStore } from '@/data/stores'
import { useActiveRun, useDerivedRun } from '@/engine'
import { formatDate, formatNumber } from '@/lib/format'
import { ApDocCard } from './ApDocCard'
import { ApSankey, type SankeySelection } from './ApSankey'
import { apListRows, apSankey, DECISION_TONE, EMPTY_FILTER, facetCounts, filterRows, isFiltering, NO_REASON, type ApFilter, type ApListRow } from './model'
import styles from './Ap.module.css'

const DOC_PARAM = 'doc'

export default function ApPage() {
  const { status, data, error } = useDerivedRun()
  const api = useDatasetStore((s) => s.api)
  const run = useActiveRun()
  return (
    <Page>
      <QueryState status={status} error={error}>
        {() => (data && api && run ? <ApInbox data={data} api={api} run={run} /> : null)}
      </QueryState>
    </Page>
  )
}

const label = (catalog: Record<string, { label: string } | undefined>, k: string) => catalog[k]?.label ?? k

function ApInbox({ data, api, run }: { data: DerivedRun; api: DatasetApi; run: RunBundle }) {
  const rows = run.deliverables.ap as ApRow[]
  const all = useMemo(() => apListRows(data.items, rows), [data.items, rows])
  const sankey = useMemo(() => apSankey(rows), [rows])
  const [filter, setFilter] = useState<ApFilter>(EMPTY_FILTER)
  const [params, setParams] = useSearchParams()
  const selectedDoc = params.get(DOC_PARAM)
  const [cursor, setCursor] = useState<string | null>(null)

  const visible = useMemo(() => filterRows(all, filter), [all, filter])
  const counts = useMemo(() => facetCounts(all, filter), [all, filter])
  const selected = all.find((r) => r.row.doc_id === selectedDoc) ?? null

  const selectDoc = (docId: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (docId) next.set(DOC_PARAM, docId)
        else next.delete(DOC_PARAM)
        return next
      },
      { replace: true, preventScrollReset: true },
    )

  const sankeySel: SankeySelection = {
    type: filter.types.length === 1 ? filter.types[0] : null,
    decision: filter.decisions.length === 1 ? filter.decisions[0] : null,
  }
  const onSankey = (sel: SankeySelection) => setFilter((f) => ({ ...f, types: sel.type ? [sel.type] : [], decisions: sel.decision ? [sel.decision] : [] }))

  const options = (m: Map<string, number>, catalog: Record<string, { label: string } | undefined>, order: readonly string[]) =>
    [...new Set([...order.filter((k) => m.has(k)), ...m.keys()])].map((k) => ({ value: k, label: k === NO_REASON ? 'Sin motivo' : label(catalog, k), count: m.get(k) ?? 0 }))

  const columns = useMemo<Column<ApListRow>[]>(
    () => [
      { id: 'doc', header: 'Documento', width: 110, cell: (r) => <Mono>{r.row.doc_id}</Mono>, sortValue: (r) => r.row.doc_id },
      { id: 'type', header: 'Tipo', width: 130, cell: (r) => label(AP_DOCUMENT_TYPE_CATALOG, r.row.document_type), sortValue: (r) => r.row.document_type },
      { id: 'vendor', header: 'Proveedor', width: 'minmax(160px, 1fr)', cell: (r) => r.item.counterparty ?? <span className={styles.muted}>{r.row.vendor_id ?? 'Sin alta'}</span>, sortValue: (r) => r.item.counterparty },
      { id: 'number', header: 'Factura', width: 120, cell: (r) => <Mono muted>{r.row.invoice_number ?? '—'}</Mono> },
      { id: 'company', header: 'Soc.', width: 60, cell: (r) => <Mono muted>{r.row.company ?? '—'}</Mono>, sortValue: (r) => r.row.company },
      { id: 'date', header: 'Fecha', width: 90, cell: (r) => formatDate(r.row.invoice_date), sortValue: (r) => r.row.invoice_date },
      { id: 'gross', header: 'Total', width: 120, align: 'right', cell: (r) => <Amount cents={r.item.amount} currency={r.item.currency ?? 'EUR'} />, sortValue: (r) => r.item.amount },
      {
        id: 'decision',
        header: 'Decisión',
        width: 150,
        cell: (r) => <Badge tone={DECISION_TONE[r.item.outcome] ?? 'neutral'}>{label(AP_DECISION_CATALOG, r.item.outcome)}</Badge>,
        sortValue: (r) => r.item.outcome,
      },
      {
        id: 'reasons',
        header: 'Motivo',
        width: 'minmax(140px, 1fr)',
        cell: (r) => (r.row.duplicate_of ? <>Duplicado de <Mono>{r.row.duplicate_of}</Mono></> : r.item.reasons.map((x) => label(AP_REASON_CATALOG, x)).join(', ') || <span className={styles.muted}>—</span>),
      },
    ],
    [],
  )

  const byDecision = useMemo(() => {
    const m = new Map<string, number>()
    for (const r of all) m.set(r.item.outcome, (m.get(r.item.outcome) ?? 0) + 1)
    return m
  }, [all])

  return (
    <>
      <PageHeader
        title="Bandeja de proveedores"
        subtitle={`${formatNumber(all.length)} documentos · ${formatNumber(byDecision.get('POST') ?? 0)} contabilizados · ${formatNumber((byDecision.get('HOLD') ?? 0) + (byDecision.get('REJECT') ?? 0) + (byDecision.get('POST_PAYMENT_BLOCK') ?? 0))} retenidos, rechazados o bloqueados`}
      />

      <Section title="Tipo de documento → decisión" description="Cada banda es el número de documentos. Pulsa una banda o un nodo para filtrar la lista.">
        <ApSankey data={sankey} selection={sankeySel} onSelect={onSankey} />
      </Section>

      <Section title="Documentos" count={visible.length}>
        <FilterBar
          onClear={isFiltering(filter) ? () => setFilter(EMPTY_FILTER) : undefined}
          end={
            <label className={styles.search}>
              <Search aria-hidden />
              <input
                type="search"
                placeholder="Documento, factura, proveedor"
                value={filter.query}
                onChange={(e) => setFilter((f) => ({ ...f, query: e.target.value }))}
                aria-label="Buscar documentos"
              />
            </label>
          }
        >
          <FilterChip
            label="Decisión"
            options={options(counts.decisions, AP_DECISION_CATALOG, Object.keys(AP_DECISION_CATALOG))}
            selected={filter.decisions}
            onChange={(decisions) => setFilter((f) => ({ ...f, decisions }))}
          />
          <FilterChip
            label="Motivo"
            options={options(counts.reasons, AP_REASON_CATALOG, [...Object.keys(AP_REASON_CATALOG), NO_REASON])}
            selected={filter.reasons}
            onChange={(reasons) => setFilter((f) => ({ ...f, reasons }))}
          />
          <FilterChip
            label="Tipo"
            options={options(counts.types, AP_DOCUMENT_TYPE_CATALOG, Object.keys(AP_DOCUMENT_TYPE_CATALOG))}
            selected={filter.types}
            onChange={(types) => setFilter((f) => ({ ...f, types }))}
          />
        </FilterBar>
        <DataTable
          aria-label="Documentos de la bandeja"
          rows={visible}
          columns={columns}
          getRowId={(r) => r.row.doc_id}
          selectedId={selectedDoc ?? cursor}
          onSelectedChange={(id) => (selected && id ? selectDoc(id) : setCursor(id))}
          onOpen={(r) => selectDoc(r.row.doc_id)}
          globalKeys
          height={400}
        />
      </Section>

      {selected && <ApDocCard key={selected.row.doc_id} api={api} item={selected.item} row={selected.row} rows={rows} onSelectDoc={selectDoc} />}
    </>
  )
}
