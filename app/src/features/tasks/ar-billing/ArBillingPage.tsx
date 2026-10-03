// `/tareas/facturacion` Facturación AR: ¿qué se factura y por cuánto?
import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { Search } from 'lucide-react'
import {
  Amount,
  Badge,
  DataTable,
  FilterBar,
  FilterChip,
  ITEM_STATUS,
  Metric,
  Mono,
  Page,
  PageHeader,
  Pill,
  QueryState,
  Section,
  StatusDot,
  type Column,
} from '@/components'
import type { ArBillingRow, CloseRow, DatasetApi, DerivedRun, RunBundle } from '@/domain/types'
import { AR_BILLING_OUTCOME_CATALOG } from '@/domain/catalog/policy'
import { useDatasetStore } from '@/data/stores'
import { effectiveDeliverables, useActiveRun, useDerivedRun } from '@/engine'
import { formatCompactMoney, formatNumber } from '@/lib/format'
import { BILLING_TYPE_LABELS, findFlowFilter, MissingTaskFile, ProcessMap, TASK_META, useProcessFlow } from '@/features/item/kit'
import { billingListRows, billingSummary, type BillingListRow } from './billingModel'
import { InvoicePreview } from './InvoicePreview'
import styles from './ArBilling.module.css'

const NODE_PARAM = 'rama'
const ITEM_PARAM = 'factura'
const TYPE_ORDER = Object.keys(BILLING_TYPE_LABELS)
const typeLabel = (t: string | null) => (t ? (BILLING_TYPE_LABELS[t] ?? t) : 'Sin tipo')
const outcomeLabel = (o: string) => AR_BILLING_OUTCOME_CATALOG[o as keyof typeof AR_BILLING_OUTCOME_CATALOG]?.label ?? o

export default function ArBillingPage() {
  const { status, data, error } = useDerivedRun()
  const api = useDatasetStore((s) => s.api)
  const run = useActiveRun()
  return (
    <Page>
      <QueryState status={status} error={error}>
        {() => (data && api && run ? !run.present.ar_billing ? <MissingTaskFile task="ar_billing" /> : <Billing data={data} api={api} run={run} /> : null)}
      </QueryState>
    </Page>
  )
}

function Billing({ data, api, run }: { data: DerivedRun; api: DatasetApi; run: RunBundle }) {
  const d = useMemo(() => effectiveDeliverables(run), [run])
  const rows = d.ar_billing as ArBillingRow[]
  const closeRows = d.close as CloseRow[]
  const all = useMemo(() => billingListRows(data.items, rows, api.core.arInbox.billing), [data.items, rows, api.core.arInbox.billing])
  const summary = useMemo(() => billingSummary(all, closeRows, api.core), [all, closeRows, api.core])
  const customers = useMemo(() => new Map(api.core.customers.map((c) => [c.id, c.name])), [api.core.customers])

  const flow = useProcessFlow('ar_billing')
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
  const [types, setTypes] = useState<string[]>([])
  const [companies, setCompanies] = useState<string[]>([])
  const [cursor, setCursor] = useState<string | null>(null)

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase()
    return all.filter(
      (r) =>
        (!nodeFilter || nodeFilter.items.has(r.item.id)) &&
        (!types.length || types.includes(r.type ?? '')) &&
        (!companies.length || companies.includes(r.item.company ?? '')) &&
        (!q || [r.item.key, r.contract, r.invoiceNumber, r.item.counterparty].some((x) => x?.toLowerCase().includes(q))),
    )
  }, [all, nodeFilter, types, companies, query])

  const count = (key: (r: BillingListRow) => string) => {
    const m = new Map<string, number>()
    for (const r of all) m.set(key(r), (m.get(key(r)) ?? 0) + 1)
    return m
  }
  const typeCounts = count((r) => r.type ?? '')
  const companyCounts = count((r) => r.item.company ?? '')

  const columns = useMemo<Column<BillingListRow>[]>(
    () => [
      { id: 'status', header: '', width: 28, cell: (r) => <StatusDot status={r.item.status} label={ITEM_STATUS[r.item.status].label} /> },
      { id: 'key', header: 'Partida', width: 216, cell: (r) => <Mono className={styles.ellipsis}>{r.item.key}</Mono>, sortValue: (r) => r.item.key },
      {
        id: 'customer',
        header: 'Cliente',
        width: 'minmax(160px, 1fr)',
        cell: (r) => <span className={styles.ellipsis}>{r.item.counterparty ?? (r.customer ? customers.get(r.customer) : null) ?? '—'}</span>,
        sortValue: (r) => r.item.counterparty,
      },
      { id: 'company', header: 'Soc.', width: 60, cell: (r) => <Mono muted>{r.item.company ?? '—'}</Mono>, sortValue: (r) => r.item.company },
      { id: 'number', header: 'Factura', width: 116, cell: (r) => <Mono muted>{r.invoiceNumber ?? '—'}</Mono>, sortValue: (r) => r.invoiceNumber },
      { id: 'tax', header: 'Imp.', width: 64, cell: (r) => <Mono muted>{r.row?.invoice?.tax_code ?? '—'}</Mono>, sortValue: (r) => r.row?.invoice?.tax_code },
      {
        id: 'net',
        header: 'Base',
        width: 156,
        align: 'right',
        cell: (r) => <Amount cents={r.row?.invoice?.net ?? null} currency={r.item.currency ?? 'EUR'} />,
        sortValue: (r) => r.row?.invoice?.net ?? null,
      },
      {
        id: 'payable',
        header: 'A cobrar',
        width: 156,
        align: 'right',
        cell: (r) => <Amount cents={r.row?.invoice?.payable ?? null} currency={r.item.currency ?? 'EUR'} />,
        sortValue: (r) => r.row?.invoice?.payable ?? null,
      },
      {
        id: 'outcome',
        header: 'Decisión',
        width: 150,
        cell: (r) => (
          <Badge tone={ITEM_STATUS[r.item.status].tone} variant="outline">
            {outcomeLabel(r.item.outcome)}
          </Badge>
        ),
        sortValue: (r) => r.item.outcome,
      },
    ],
    [customers],
  )

  const filtering = !!nodeFilter || types.length > 0 || companies.length > 0 || query !== ''
  const clear = () => {
    setParam(NODE_PARAM, null)
    setTypes([])
    setCompanies([])
    setQuery('')
  }

  return (
    <>
      <PageHeader
        title={TASK_META.ar_billing.title}
        subtitle={`${formatNumber(all.length)} partidas · ${formatNumber(summary.invoices)} facturas · ${formatNumber(summary.pending)} ${summary.pending === 1 ? 'pendiente' : 'pendientes'} de aprobación`}
      />

      <div className={styles.metrics}>
        <Metric label="Base facturada" value={formatCompactMoney(summary.netEur)} comparison="en EUR" hint="Suma de la base imponible de las facturas del mes; 3100 convertida a EUR al tipo de cierre." />
        <Metric label="A cobrar" value={formatCompactMoney(summary.payableEur)} comparison="tras retenciones y deducciones" hint="Total con impuestos menos retención de garantía, 5 al millar y amortización del anticipo, en EUR." />
        <Metric label="Por FACe" value={formatNumber(summary.face)} comparison={`de ${formatNumber(summary.invoices)} facturas`} hint="Facturas a clientes públicos españoles con sus tres códigos DIR3." />
        <Metric
          label="Obra pendiente de certificar"
          value={formatCompactMoney(summary.wipEur)}
          comparison={summary.pendingWithoutWip ? `${formatNumber(summary.pendingWithoutWip)} sin registrar en Cierre` : 'registrada en Cierre'}
          hint="Certificaciones sin aprobar: no se facturan y su obra se periodifica como WIP_REVENUE en el cierre."
        />
      </div>

      {flow && (
        <Section title="Mapa de decisión" description="Cuántas partidas tomaron cada camino de la política. Pulsa una rama para filtrar la lista.">
          <ProcessMap flow={flow} selectedId={nodeId} onSelect={(f) => setParam(NODE_PARAM, f?.id ?? null)} />
        </Section>
      )}

      <Section title="Partidas" count={visible.length}>
        <FilterBar
          onClear={filtering ? clear : undefined}
          end={
            <label className={styles.search}>
              <Search aria-hidden />
              <input type="search" placeholder="Partida, contrato, factura, cliente" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Buscar partidas" />
            </label>
          }
        >
          {nodeFilter && (
            <Pill tone="brand" onRemove={() => setParam(NODE_PARAM, null)} removeLabel="Quitar filtro del mapa">
              Mapa: {nodeFilter.label}
            </Pill>
          )}
          <FilterChip
            label="Tipo"
            options={[...TYPE_ORDER.filter((t) => typeCounts.has(t)), ...[...typeCounts.keys()].filter((t) => !TYPE_ORDER.includes(t))].map((t) => ({
              value: t,
              label: typeLabel(t || null),
              count: typeCounts.get(t),
            }))}
            selected={types}
            onChange={setTypes}
          />
          <FilterChip
            label="Sociedad"
            options={[...companyCounts].sort((a, b) => a[0].localeCompare(b[0])).map(([c, n]) => ({ value: c, label: c || '—', count: n }))}
            selected={companies}
            onChange={setCompanies}
          />
        </FilterBar>
        <DataTable
          aria-label="Partidas de facturación"
          rows={visible}
          columns={columns}
          getRowId={(r) => r.item.key}
          groupBy={(r) => r.type ?? ''}
          groupOrder={TYPE_ORDER}
          renderGroup={(k) => typeLabel(k || null)}
          selectedId={selected?.item.key ?? cursor}
          onSelectedChange={(id) => (selected && id ? setParam(ITEM_PARAM, id) : setCursor(id))}
          onOpen={(r) => setParam(ITEM_PARAM, r.item.key)}
          globalKeys
          height={420}
        />
      </Section>

      {selected && <InvoicePreview key={selected.item.key} entry={selected} api={api} closeRows={closeRows} onClose={() => setParam(ITEM_PARAM, null)} />}
    </>
  )
}
