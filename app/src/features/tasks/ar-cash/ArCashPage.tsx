// `/tareas/cobros` Aplicación de cobros: ¿qué paga cada abono?
import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { Search } from 'lucide-react'
import {
  Amount,
  Badge,
  DataTable,
  FilterBar,
  FilterChip,
  Mono,
  Page,
  PageHeader,
  Pill,
  ProgressBar,
  QueryState,
  Section,
  type Column,
  type Tone,
} from '@/components'
import type { ArCashRow, ArResidualType, DatasetApi, DerivedRun, RunBundle, WorkItem } from '@/domain/types'
import { AR_CASH_OUTCOME_CATALOG, AR_RESIDUAL_CATALOG } from '@/domain/catalog/policy'
import { useDatasetStore } from '@/data/stores'
import { effectiveDeliverables, useActiveRun, useDerivedRun } from '@/engine'
import { formatDate, formatNumber } from '@/lib/format'
import { findFlowFilter, MissingTaskFile, ProcessMap, TASK_META, useProcessFlow } from '@/features/item/kit'
import { allocation, suspenseClearing, type Allocation, type SuspenseClearing } from './cashModel'
import { ReceiptDetail } from './ReceiptDetail'
import styles from './ArCash.module.css'

const NODE_PARAM = 'rama'
const ITEM_PARAM = 'cobro'
const outcomeLabel = (o: string) => AR_CASH_OUTCOME_CATALOG[o as keyof typeof AR_CASH_OUTCOME_CATALOG]?.label ?? o
const residualLabel = (t: string) => AR_RESIDUAL_CATALOG[t as ArResidualType]?.label ?? t
const OUTCOME_TONE: Record<string, Tone> = { APPLIED: 'ok', APPLIED_WITH_DIFFERENCES: 'info', PARTIAL: 'warn', NOT_APPLIED: 'danger' }

interface ReceiptRow {
  item: WorkItem
  row: ArCashRow
  allocation: Allocation
}

export default function ArCashPage() {
  const { status, data, error } = useDerivedRun()
  const api = useDatasetStore((s) => s.api)
  const run = useActiveRun()
  return (
    <Page>
      <QueryState status={status} error={error}>
        {() => (data && api && run ? !run.present.ar_cash ? <MissingTaskFile task="ar_cash" /> : <Cash data={data} api={api} run={run} /> : null)}
      </QueryState>
    </Page>
  )
}

function Cash({ data, api, run }: { data: DerivedRun; api: DatasetApi; run: RunBundle }) {
  const d = useMemo(() => effectiveDeliverables(run), [run])
  const rows = d.ar_cash as ArCashRow[]
  const items = useMemo(() => data.items.filter((it) => it.task === 'ar_cash'), [data.items])
  const all = useMemo<ReceiptRow[]>(
    () => items.map((item) => ({ item, row: rows[item.rowIndex], allocation: allocation(rows[item.rowIndex], item.amount ?? 0) })),
    [items, rows],
  )
  const clearing = useMemo(() => suspenseClearing(items, rows, api.core), [items, rows, api.core])
  const billingEntries = useMemo(() => d.ar_billing.flatMap((r) => (r.journal_entry ? [r.journal_entry] : [])), [d.ar_billing])

  const flow = useProcessFlow('ar_cash')
  const [params, setParams] = useSearchParams()
  const setParam = useCallback(
    (name: string, value: string | null) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev)
          if (value) next.set(name, value)
          else next.delete(name)
          return next
        },
        { replace: true, preventScrollReset: true },
      ),
    [setParams],
  )
  const nodeId = params.get(NODE_PARAM)
  const nodeFilter = findFlowFilter(flow, nodeId)
  const selectedKey = params.get(ITEM_PARAM)
  const selected = all.find((r) => r.item.key === selectedKey) ?? null

  const [query, setQuery] = useState('')
  const [outcomes, setOutcomes] = useState<string[]>([])
  const [companies, setCompanies] = useState<string[]>([])
  const [cursor, setCursor] = useState<string | null>(null)

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return all.filter(
      (r) =>
        (!nodeFilter || nodeFilter.items.has(r.item.id)) &&
        (!outcomes.length || outcomes.includes(r.item.outcome)) &&
        (!companies.length || companies.includes(r.item.company ?? '')) &&
        (!q ||
          [r.item.key, r.item.counterparty, r.row?.customer, ...(r.row?.applications ?? []).map((a) => a.invoice ?? a.pagare)].some((x) =>
            x?.toLowerCase().includes(q),
          )),
    )
  }, [all, nodeFilter, outcomes, companies, query])

  const count = (key: (r: ReceiptRow) => string) => {
    const m = new Map<string, number>()
    for (const r of all) m.set(key(r), (m.get(key(r)) ?? 0) + 1)
    return m
  }
  const outcomeCounts = count((r) => r.item.outcome)
  const companyCounts = count((r) => r.item.company ?? '')
  const withDifferences = all.filter((r) => r.item.reasons.length > 0).length
  const nonCustomer = all.filter((r) => r.row?.customer == null).length

  const columns = useMemo<Column<ReceiptRow>[]>(
    () => [
      { id: 'key', header: 'Línea', width: 104, cell: (r) => <Mono>{r.item.key}</Mono>, sortValue: (r) => r.item.key },
      { id: 'date', header: 'Fecha', width: 92, cell: (r) => formatDate(r.item.date), sortValue: (r) => r.item.date },
      {
        id: 'customer',
        header: 'Cliente',
        width: 'minmax(180px, 1fr)',
        cell: (r) => <span className={styles.ellipsis}>{r.item.counterparty ?? <span className={styles.muted}>No es cliente</span>}</span>,
        sortValue: (r) => r.item.counterparty,
      },
      { id: 'company', header: 'Soc.', width: 60, cell: (r) => <Mono muted>{r.item.company ?? '—'}</Mono>, sortValue: (r) => r.item.company },
      { id: 'amount', header: 'Importe', width: 140, align: 'right', cell: (r) => <Amount cents={r.item.amount} currency={r.item.currency ?? 'EUR'} />, sortValue: (r) => r.item.amount },
      {
        id: 'split',
        header: 'Reparto',
        width: 150,
        cell: (r) => (
          <ProgressBar
            size="sm"
            className={styles.split}
            label={`Reparto de ${r.item.key}`}
            segments={r.allocation.uses.map((f) => ({ value: f.amount, tone: f.tone, label: f.label }))}
          />
        ),
      },
      {
        id: 'outcome',
        header: 'Resultado',
        width: 168,
        cell: (r) => (
          <Badge tone={OUTCOME_TONE[r.item.outcome] ?? 'neutral'} variant="outline">
            {outcomeLabel(r.item.outcome)}
          </Badge>
        ),
        sortValue: (r) => r.item.outcome,
      },
      {
        id: 'residuals',
        header: 'Diferencias',
        width: 'minmax(150px, 1fr)',
        cell: (r) => <span className={styles.ellipsis}>{r.item.reasons.map(residualLabel).join(', ') || <span className={styles.muted}>—</span>}</span>,
      },
    ],
    [],
  )

  const filtering = !!nodeFilter || outcomes.length > 0 || companies.length > 0 || query !== ''
  const clear = () => {
    setParam(NODE_PARAM, null)
    setOutcomes([])
    setCompanies([])
    setQuery('')
  }

  return (
    <>
      <PageHeader
        title={TASK_META.ar_cash.title}
        subtitle={`${formatNumber(all.length)} abonos · ${formatNumber(withDifferences)} con diferencias · ${formatNumber(nonCustomer)} no son de clientes`}
      />

      {flow && (
        <Section title="Mapa de decisión" description="Cuántos abonos tomaron cada camino de la política. Pulsa una rama para filtrar la lista.">
          <ProcessMap flow={flow} selectedId={nodeId} onSelect={(f) => setParam(NODE_PARAM, f?.id ?? null)} />
        </Section>
      )}

      <Section
        title="Vaciado de la 55500000"
        description="Los abonos entraron en Dr 572 / Cr 55500000 al importar el extracto. El asiento de ajuste de cada cobro la vacía contra las facturas o las diferencias."
      >
        <SuspenseBars clearing={clearing} />
      </Section>

      <Section title="Abonos" count={visible.length}>
        <FilterBar
          onClear={filtering ? clear : undefined}
          end={
            <label className={styles.search}>
              <Search aria-hidden />
              <input type="search" placeholder="Línea, cliente, factura" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Buscar abonos" />
            </label>
          }
        >
          {nodeFilter && (
            <Pill tone="brand" onRemove={() => setParam(NODE_PARAM, null)} removeLabel="Quitar filtro del mapa">
              Mapa: {nodeFilter.label}
            </Pill>
          )}
          <FilterChip
            label="Resultado"
            options={Object.keys(AR_CASH_OUTCOME_CATALOG)
              .filter((o) => outcomeCounts.has(o))
              .map((o) => ({ value: o, label: outcomeLabel(o), count: outcomeCounts.get(o) }))}
            selected={outcomes}
            onChange={setOutcomes}
          />
          <FilterChip
            label="Sociedad"
            options={[...companyCounts].sort((a, b) => a[0].localeCompare(b[0])).map(([c, n]) => ({ value: c, label: c || '—', count: n }))}
            selected={companies}
            onChange={setCompanies}
          />
        </FilterBar>
        <DataTable
          aria-label="Abonos"
          rows={visible}
          columns={columns}
          getRowId={(r) => r.item.key}
          selectedId={selected?.item.key ?? cursor}
          onSelectedChange={(id) => (selected && id ? setParam(ITEM_PARAM, id) : setCursor(id))}
          onOpen={(r) => setParam(ITEM_PARAM, r.item.key)}
          globalKeys
          height={420}
        />
      </Section>

      {selected && (
        <ReceiptDetail
          key={selected.item.key}
          item={selected.item}
          row={selected.row}
          allocation={selected.allocation}
          items={items}
          rows={rows}
          billingEntries={billingEntries}
          api={api}
          onClose={() => setParam(ITEM_PARAM, null)}
        />
      )}
    </>
  )
}

function SuspenseBars({ clearing }: { clearing: SuspenseClearing[] }) {
  if (!clearing.length) return <p className={styles.muted}>No hay abonos en la ejecución.</p>
  return (
    <ul className={styles.suspense}>
      {clearing.map((c) => (
        <li key={c.company}>
          <span className={styles.suspenseCompany}>
            <Mono>{c.company}</Mono>
            <span className={styles.muted}>
              {formatNumber(c.receipts)} {c.receipts === 1 ? 'abono' : 'abonos'}
            </span>
          </span>
          <ProgressBar
            label={`55500000 de ${c.company}`}
            total={Math.max(c.received, c.cleared)}
            segments={[
              { value: Math.min(c.cleared, c.received), tone: 'ok', label: 'Aplicado' },
              { value: Math.max(c.remaining, 0), tone: 'danger', label: 'Queda en 55500000' },
            ]}
          />
          <span className={styles.suspenseFigures}>
            <Amount cents={c.received} currency={c.currency} />
            {c.remaining === 0 ? (
              <Badge tone="ok" variant="outline">
                Vacía
              </Badge>
            ) : (
              <Badge tone="danger" variant="outline">
                Queda <Amount cents={c.remaining} currency={c.currency} />
              </Badge>
            )}
          </span>
        </li>
      ))}
    </ul>
  )
}
