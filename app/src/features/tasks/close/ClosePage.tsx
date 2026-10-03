// `/tareas/cierre` Cierre: ¿qué falta registrar a fin de mes? Process map, then one view per close type.
import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router'
import { PanelRight } from 'lucide-react'
import { Amount, Badge, Button, DataTable, Mono, Page, PageHeader, QueryState, Section, Sparkline, Tabs, type Column } from '@/components'
import type { CloseRow, DatasetCore, DerivedRun, RunBundle, WorkItem } from '@/domain/types'
import { CLOSE_TYPES } from '@/domain/types'
import { CLOSE_TYPE_CATALOG } from '@/domain/catalog/policy'
import { useDatasetStore } from '@/data/stores'
import { effectiveDeliverables, useActiveRun, useDerivedRun } from '@/engine'
import { findFlowFilter, MissingTaskFile, ProcessMap, useProcessFlow } from '@/features/item/kit'
import { formatDate, formatMonth, formatNumber } from '@/lib/format'
import { useActiveItemId, useOpenItem } from '@/shell/useOpenItem'
import { AGING_LABEL, agingOf, closeKeyValue, closeRowsOf, fxBreakdown, monthEndOf, prepaidFraction, vendorHistory, type AgingBucket } from './model'
import styles from './Close.module.css'

export default function ClosePage() {
  const { status, data, error } = useDerivedRun()
  const core = useDatasetStore((s) => s.api?.core ?? null)
  const run = useActiveRun()
  return (
    <Page>
      <QueryState status={status} error={error}>
        {() => (data && core && run ? !run.present.close ? <MissingTaskFile task="close" /> : <Close data={data} core={core} run={run} /> : null)}
      </QueryState>
    </Page>
  )
}

const typeLabel = (type: string) => CLOSE_TYPE_CATALOG[type as keyof typeof CLOSE_TYPE_CATALOG]?.label ?? type

interface TypeViewProps {
  items: WorkItem[]
  rows: (item: WorkItem) => CloseRow[]
  core: DatasetCore
  review: ReadonlySet<string>
  itemsById: DerivedRun['itemsById']
}

function Close({ data, core, run }: { data: DerivedRun; core: DatasetCore; run: RunBundle }) {
  const all = useMemo(() => data.items.filter((it) => it.task === 'close'), [data.items])
  const delivered = useMemo(() => effectiveDeliverables(run).close as CloseRow[], [run])
  const rows = useMemo(() => {
    const cache = new Map<string, CloseRow[]>()
    return (item: WorkItem) => {
      let r = cache.get(item.id)
      if (!r) cache.set(item.id, (r = closeRowsOf(delivered, item)))
      return r
    }
  }, [delivered])
  const review = useMemo(() => new Set(data.attention.map((a) => a.item)), [data.attention])
  const [params, setParams] = useSearchParams()
  const setParam = (key: string, value: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value) next.set(key, value)
        else next.delete(key)
        return next
      },
      { replace: true, preventScrollReset: true },
    )
  const flow = useProcessFlow('close')
  const node = params.get('nodo')
  const nodeFilter = findFlowFilter(flow, node)
  const items = useMemo(() => (nodeFilter ? all.filter((it) => nodeFilter.items.has(it.id)) : all), [all, nodeFilter])
  const steps = core.tasks.close.steps?.length ? core.tasks.close.steps : [...CLOSE_TYPES]
  const tabs = steps.map((t) => ({ id: t, label: typeLabel(t), count: items.filter((it) => it.outcome === t).length }))
  const active = useActiveItemId()
  const activeType = active?.startsWith('close:') ? active.slice('close:'.length).split('/')[0] : null
  const type = steps.find((t) => t === params.get('tipo')) ?? steps.find((t) => t === activeType) ?? tabs.find((t) => t.count)?.id ?? steps[0]
  const typeItems = useMemo(() => items.filter((it) => it.outcome === type), [items, type])
  const month = core.tasks.close.month
  const view: TypeViewProps = { items: typeItems, rows, core, review, itemsById: data.itemsById }

  return (
    <>
      <PageHeader title="Cierre" subtitle={`${formatNumber(all.length)} partidas de ${formatMonth(month)}, fechadas el ${formatDate(monthEndOf(month))}. Sus retrocesiones del día 1 no se entregan.`} />
      {flow && (
        <Section title={flow.title} description="Qué tipo de partida es cada una y cuáles pasan a revisión. Pulsa una rama para filtrar.">
          <ProcessMap flow={flow} selectedId={node} onSelect={(f) => setParam('nodo', f?.id ?? null)} />
        </Section>
      )}
      <Section
        title={typeLabel(type)}
        description={CLOSE_TYPE_CATALOG[type as keyof typeof CLOSE_TYPE_CATALOG]?.description}
        count={view.items.length}
      >
        <Tabs aria-label="Tipos de partida de cierre" tabs={tabs} value={type} onChange={(t) => setParam('tipo', t)} />
        {view.items.length === 0 ? (
          <p className={styles.muted}>{nodeFilter ? `Ninguna partida de este tipo en «${nodeFilter.label}».` : 'Ninguna partida de este tipo este mes.'}</p>
        ) : type === 'ACCRUAL' ? (
          <Accruals {...view} />
        ) : type === 'PREPAID' ? (
          <Prepaid {...view} />
        ) : type === 'FX_REVAL' ? (
          <FxReval {...view} />
        ) : type === 'BAD_DEBT' ? (
          <BadDebt {...view} />
        ) : (
          <Simple {...view} />
        )}
      </Section>
    </>
  )
}

// ---------------------------------------------------------------- shared

function useNames(core: DatasetCore) {
  return useMemo(() => {
    const vendors = new Map(core.vendors.map((v) => [v.id, v.name]))
    const customers = new Map(core.customers.map((c) => [c.id, c.name]))
    return { vendor: (id: string) => vendors.get(id) ?? id, customer: (id: string) => customers.get(id) ?? id }
  }, [core.vendors, core.customers])
}

function ItemTable({ label, items, columns }: { label: string; items: WorkItem[]; columns: Column<WorkItem>[] }) {
  const openItem = useOpenItem()
  const active = useActiveItemId()
  return (
    <DataTable
      aria-label={label}
      rows={items}
      columns={columns}
      getRowId={(it) => it.id}
      selectedId={active}
      onSelectedChange={(id) => active && id && openItem(id)}
      onOpen={(it) => openItem(it.id)}
      height={Math.min(560, 34 + Math.max(items.length, 3) * 36)}
      globalKeys
    />
  )
}

const amountColumn = (header = 'Importe'): Column<WorkItem> => ({
  id: 'amount',
  header,
  width: 140,
  align: 'right',
  cell: (it) => <Amount cents={it.amount} currency={it.currency ?? 'EUR'} />,
  sortValue: (it) => it.amount,
})

const companyColumn: Column<WorkItem> = { id: 'company', header: 'Sociedad', width: 84, cell: (it) => <Mono>{it.company ?? '—'}</Mono>, sortValue: (it) => it.company }

const reviewColumn = (review: ReadonlySet<string>): Column<WorkItem> => ({
  id: 'review',
  header: 'Revisión',
  width: 110,
  cell: (it) => (review.has(it.id) ? <Badge tone="warn">A revisar</Badge> : null),
  sortValue: (it) => (review.has(it.id) ? 1 : 0),
})

// ---------------------------------------------------------------- accruals

function Accruals({ items, rows, core, review }: TypeViewProps) {
  const names = useNames(core)
  const month = core.tasks.close.month
  const history = useMemo(() => new Map(items.map((it) => [it.id, vendorHistory(core.apInvoices, closeKeyValue(it), it.company ?? '', month)])), [items, core.apInvoices, month])
  const columns = useMemo<Column<WorkItem>[]>(
    () => [
      {
        id: 'vendor',
        header: 'Proveedor',
        width: 'minmax(220px, 1.5fr)',
        cell: (it) => (
          <span className={styles.party}>
            <Link to={`/datos/proveedores/${encodeURIComponent(closeKeyValue(it))}`} className={styles.link} onClick={(e) => e.stopPropagation()}>
              <Mono>{closeKeyValue(it)}</Mono>
            </Link>
            <span className={styles.ellipsis}>{names.vendor(closeKeyValue(it))}</span>
          </span>
        ),
        sortValue: (it) => names.vendor(closeKeyValue(it)),
      },
      companyColumn,
      {
        id: 'history',
        header: 'Facturado, 12 meses',
        width: 150,
        cell: (it) => {
          const h = history.get(it.id)!
          return h.average === null ? <span className={styles.muted}>Sin facturas</span> : <Sparkline values={h.values} width={120} height={20} aria-label={`Neto facturado por mes de ${closeKeyValue(it)}`} />
        },
      },
      {
        id: 'average',
        header: 'Media mensual',
        width: 130,
        align: 'right',
        cell: (it) => <Amount cents={history.get(it.id)!.average} currency={it.currency ?? 'EUR'} />,
        sortValue: (it) => history.get(it.id)!.average,
      },
      amountColumn('Periodificado'),
      {
        id: 'ratio',
        header: '× media',
        width: 80,
        align: 'right',
        cell: (it) => {
          const avg = history.get(it.id)!.average
          return avg ? <span className="tabular">{formatNumber((it.amount ?? 0) / avg, { decimals: 2 })}</span> : null
        },
        sortValue: (it) => {
          const avg = history.get(it.id)!.average
          return avg ? (it.amount ?? 0) / avg : null
        },
      },
      { id: 'rows', header: 'Tramos', width: 70, align: 'right', cell: (it) => rows(it).length, sortValue: (it) => rows(it).length },
      reviewColumn(review),
    ],
    [names, history, rows, review],
  )
  return (
<ItemTable label="Periodificaciones" items={items} columns={columns} />
  )
}

// ---------------------------------------------------------------- prepaid

function Calendar({ k, n }: { k: number; n: number }) {
  return (
    <span className={styles.calendar} role="img" aria-label={`Mes ${k} de ${n}`}>
      {Array.from({ length: n }, (_, i) => (
        <span key={i} className={styles.month} data-state={i + 1 < k ? 'past' : i + 1 === k ? 'now' : 'next'} />
      ))}
      <span className={styles.fraction}>
        {k}/{n}
      </span>
    </span>
  )
}

function Prepaid({ items, rows, core, review, itemsById }: TypeViewProps) {
  const names = useNames(core)
  const invoices = useMemo(() => new Map(core.apInvoices.map((i) => [i.doc_id, i])), [core.apInvoices])
  const columns = useMemo<Column<WorkItem>[]>(
    () => [
      { id: 'invoice', header: 'Factura', width: 120, cell: (it) => <Mono>{closeKeyValue(it)}</Mono>, sortValue: (it) => closeKeyValue(it) },
      {
        id: 'vendor',
        header: 'Proveedor',
        width: 'minmax(200px, 1.5fr)',
        cell: (it) => {
          const doc = closeKeyValue(it)
          const inv = invoices.get(doc)
          const name = inv ? names.vendor(inv.vendor) : itemsById.get(`ap:${doc}`)?.counterparty
          return name ? <span className={styles.ellipsis}>{name}</span> : <span className={styles.muted}>—</span>
        },
      },
      companyColumn,
      { id: 'kind', header: 'Movimiento', width: 130, cell: (it) => ((it.amount ?? 0) >= 0 ? 'Diferimiento' : 'Imputación'), sortValue: (it) => Math.sign(it.amount ?? 0) },
      {
        id: 'calendar',
        header: 'Cobertura',
        width: 'minmax(160px, 1fr)',
        cell: (it) => {
          const f = prepaidFraction(rows(it)[0]?.journal_entry?.header_text as string | undefined)
          return f ? <Calendar {...f} /> : <span className={styles.muted}>—</span>
        },
      },
      { ...amountColumn('Variación 48000000'), cell: (it) => <Amount cents={it.amount} currency={it.currency ?? 'EUR'} signed /> },
      reviewColumn(review),
    ],
    [names, invoices, rows, review, itemsById],
  )
  return (
    <>
      <p className={styles.note}>En el mes de la factura se difiere la parte no devengada (importe positivo); cada mes siguiente se imputa una mensualidad (negativo).</p>
      <ItemTable label="Gastos anticipados" items={items} columns={columns} />
    </>
  )
}

// ---------------------------------------------------------------- FX revaluation

function FxReval({ items, rows, review }: TypeViewProps) {
  const fx = useMemo(() => new Map(items.map((it) => [it.id, fxBreakdown(rows(it)[0] ?? {})])), [items, rows])
  const columns = useMemo<Column<WorkItem>[]>(
    () => [
      { id: 'item', header: 'Partida', width: 'minmax(170px, 1fr)', cell: (it) => <Mono>{closeKeyValue(it)}</Mono>, sortValue: (it) => closeKeyValue(it) },
      companyColumn,
      {
        id: 'foreign',
        header: 'Abierto en divisa',
        width: 150,
        align: 'right',
        cell: (it) => {
          const f = fx.get(it.id)
          return f ? <Amount cents={f.foreign} currency={f.currency} /> : <span className={styles.muted}>—</span>
        },
      },
      {
        id: 'rate',
        header: 'Tipo de cierre',
        width: 110,
        align: 'right',
        cell: (it) => {
          const f = fx.get(it.id)
          return f ? <span className="tabular">{formatNumber(f.rate, { decimals: 6 })}</span> : null
        },
      },
      { id: 'value', header: 'Valor a cierre', width: 150, align: 'right', cell: (it) => <Amount cents={fx.get(it.id)?.value ?? null} currency={it.currency ?? 'EUR'} /> },
      { id: 'book', header: 'Valor contable', width: 150, align: 'right', cell: (it) => <Amount cents={fx.get(it.id)?.book ?? null} currency={it.currency ?? 'EUR'} /> },
      { ...amountColumn('Valoración'), cell: (it) => <Amount cents={it.amount} currency={it.currency ?? 'EUR'} signed colorize /> },
      reviewColumn(review),
    ],
    [fx, review],
  )
  return (
    <>
      <p className={styles.note}>
        Valor a tipo de cierre − valor contable, en moneda local; positivo si aumenta el valor de la partida. 3100 está en MXN: su préstamo y sus intereses en EUR se valoran aquí.
      </p>
      <ItemTable label="Valoración en divisa" items={items} columns={columns} />
    </>
  )
}

// ---------------------------------------------------------------- bad debt

const BUCKETS: AgingBucket[] = ['over365', 'over180', 'current']

function BadDebt({ items, rows, core }: TypeViewProps) {
  const names = useNames(core)
  const openItem = useOpenItem()
  const monthEnd = monthEndOf(core.tasks.close.month)
  return (
    <div className={styles.cards}>
      {items.map((it) => {
        const customer = closeKeyValue(it)
        const master = core.customers.find((c) => c.id === customer)
        const insolvent = !!master?.insolvency && master.insolvency.declared_on <= monthEnd
        const aging = agingOf(core.openItems, core.arInvoices, customer, it.company ?? '', monthEnd, insolvent)
        const row = (rows(it)[0] ?? {}) as CloseRow & { target?: number; previous?: number }
        const cur = it.currency ?? 'EUR'
        return (
          <div key={it.id} className={styles.card}>
            <div className={styles.cardHead}>
              <div>
                <Link to={`/datos/clientes/${encodeURIComponent(customer)}`} className={styles.link}>
                  <Mono>{customer}</Mono>
                </Link>{' '}
                {names.customer(customer)} · <Mono muted>{it.company}</Mono>
                {insolvent && (
                  <Badge tone="danger" className={styles.badge}>
                    Concurso desde {formatDate(master!.insolvency!.declared_on)}
                  </Badge>
                )}
              </div>
              <Button size="sm" leadingIcon={<PanelRight />} onClick={() => openItem(it.id)}>
                Abrir la partida
              </Button>
            </div>
            <div className={styles.buckets}>
              {BUCKETS.map((b) => (
                <div key={b} className={styles.bucket} data-bucket={b}>
                  <span className={styles.bucketLabel}>{AGING_LABEL[b]}</span>
                  <Amount cents={aging.totals[b]} currency={cur} />
                </div>
              ))}
            </div>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Factura</th>
                  <th>Vencimiento</th>
                  <th className={styles.num}>Días</th>
                  <th className={styles.num}>Pendiente</th>
                  <th className={styles.num}>Provisión</th>
                </tr>
              </thead>
              <tbody>
                {aging.lines.map((l) => (
                  <tr key={l.invoice}>
                    <td>
                      <Mono>{l.invoice}</Mono>
                    </td>
                    <td>{l.due ? formatDate(l.due) : '—'}</td>
                    <td className={styles.num}>{l.days ?? '—'}</td>
                    <td className={styles.num}>
                      <Amount cents={l.balance} currency={cur} />
                    </td>
                    <td className={styles.num}>
                      <Amount cents={l.required} currency={cur} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <dl className={styles.facts}>
              <div>
                <dt>Provisión necesaria</dt>
                <dd>
                  <Amount cents={typeof row.target === 'number' ? row.target : aging.required} currency={cur} />
                  {typeof row.target === 'number' && row.target !== aging.required && <Badge tone="warn">Partidas abiertas: {formatNumber(aging.required / 100, { decimals: 2 })}</Badge>}
                </dd>
              </div>
              <div>
                <dt>Provisión anterior</dt>
                <dd>{typeof row.previous === 'number' ? <Amount cents={row.previous} currency={cur} /> : '—'}</dd>
              </div>
              <div>
                <dt>Dotación del mes</dt>
                <dd>
                  <Amount cents={it.amount} currency={cur} signed colorize />
                </dd>
              </div>
            </dl>
          </div>
        )
      })}
      <p className={styles.note}>Solo clientes privados y comunidades. Antigüedad sobre las partidas abiertas de 43000000 del maestro, con umbrales estrictos sobre el vencimiento.</p>
    </div>
  )
}

// ---------------------------------------------------------------- WIP and reclassification

function Simple({ items, core, review }: TypeViewProps) {
  const names = useNames(core)
  const columns = useMemo<Column<WorkItem>[]>(
    () => [
      {
        id: 'key',
        header: 'Referencia',
        width: 'minmax(220px, 1.5fr)',
        cell: (it) =>
          it.outcome === 'WIP_REVENUE' ? (
            <Link to={`/datos/documentos/${encodeURIComponent(closeKeyValue(it))}`} className={styles.link} onClick={(e) => e.stopPropagation()}>
              <Mono>{closeKeyValue(it)}</Mono>
            </Link>
          ) : (
            <Mono>{closeKeyValue(it)}</Mono>
          ),
        sortValue: (it) => closeKeyValue(it),
      },
      { id: 'party', header: 'Cliente', width: 'minmax(200px, 1.5fr)', cell: (it) => <span className={styles.ellipsis}>{it.counterparty ?? (it.outcome === 'DOUBTFUL_RECLASS' ? names.customer(closeKeyValue(it)) : '—')}</span> },
      companyColumn,
      amountColumn(),
      reviewColumn(review),
    ],
    [names, review],
  )
  return <ItemTable label="Partidas de cierre" items={items} columns={columns} />
}
