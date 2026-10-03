import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { ChevronDown, ChevronUp, Search } from 'lucide-react'
import type { DerivedRun, TaskKey, WorkItem } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import {
  Amount,
  Badge,
  ConfidenceBand,
  DataTable,
  FilterBar,
  FilterChip,
  IconButton,
  ITEM_STATUS,
  ITEM_STATUS_ORDER,
  Mono,
  Page,
  PageHeader,
  Pill,
  ProvenanceBadge,
  QueryState,
  SegmentedControl,
  StatusDot,
  TabPanel,
  Tabs,
  ViewOptions,
  type Column,
  type SortState,
} from '@/components'
import { useDerivedRun } from '@/engine'
import { useActiveItemId, useOpenItem } from '@/shell/useOpenItem'
import { formatNumber } from '@/lib/format'
import { findFlowFilter, ProcessMap, TASK_META, useProcessFlow, type FlowFilter } from '@/features/item/kit'
import { applyActivityParams, CLEARED, countBy, filterItems, outcomeKey, outcomeLabel, parseActivityParams, type ActivityFilters } from './activityModel'
import { EventFeed } from './EventFeed'
import styles from './ActivityPage.module.css'

const TAB_PREFIX = 'activity'
const taskLabel = (t: TaskKey) => TASK_META[t].label

export default function ActivityPage() {
  const { data, status, error } = useDerivedRun()
  const [params, setParams] = useSearchParams()
  const filters = useMemo(() => parseActivityParams(params), [params])
  const update = useCallback((patch: Partial<ActivityFilters>) => setParams((prev) => applyActivityParams(prev, patch), { replace: true, preventScrollReset: true }), [setParams])

  const taskOptions = useMemo(
    () => [{ value: 'all', label: 'Todas' }, ...TASK_KEYS.map((t) => ({ value: t, label: t === 'ap' ? 'AP' : TASK_META[t].label }))],
    [],
  )

  return (
    <Page fill>
      <PageHeader
        title="Actividad"
        subtitle="Cada decisión del agente, con su razonamiento y su evidencia."
        actions={
          <SegmentedControl
            aria-label="Tarea"
            size="sm"
            options={taskOptions}
            value={filters.task ?? 'all'}
            onChange={(v) => update({ task: v === 'all' ? null : (v as TaskKey), node: null, outcome: [] })}
          />
        }
      />
      <QueryState status={status} error={error} isEmpty={!!data && data.items.length === 0}>
        {() => data && <Activity data={data} filters={filters} update={update} />}
      </QueryState>
    </Page>
  )
}

interface ActivityProps {
  data: DerivedRun
  filters: ActivityFilters
  update: (patch: Partial<ActivityFilters>) => void
}

function Activity({ data, filters, update }: ActivityProps) {
  const flow = useProcessFlow(filters.task)
  const nodeFilter = findFlowFilter(flow, filters.node)
  const [mapOpen, setMapOpen] = useState(true)
  const taskItems = useMemo(() => (filters.task ? data.items.filter((i) => i.task === filters.task) : data.items), [data.items, filters.task])
  const taskEvents = useMemo(() => (filters.task ? data.events.filter((e) => e.item.startsWith(`${filters.task}:`)) : data.events), [data.events, filters.task])

  return (
    <>
      {flow && (
        <section className={styles.map} aria-label="Mapa de decisión">
          <header className={styles.mapHeader}>
            <div className={styles.mapTitle}>
              <h2>{flow.title}</h2>
              <span>Cuántas partidas tomaron cada camino de la política. Pulsa una rama para filtrar la lista.</span>
            </div>
            <IconButton
              icon={mapOpen ? <ChevronUp /> : <ChevronDown />}
              label={mapOpen ? 'Ocultar mapa' : 'Mostrar mapa'}
              size="sm"
              onClick={() => setMapOpen((o) => !o)}
            />
          </header>
          {mapOpen && <ProcessMap flow={flow} selectedId={filters.node} onSelect={(f: FlowFilter | null) => update({ node: f?.id ?? null, view: 'items' })} />}
        </section>
      )}
      <Tabs
        idPrefix={TAB_PREFIX}
        aria-label="Vista de actividad"
        value={filters.view}
        onChange={(v) => update({ view: v as ActivityFilters['view'], group: null })}
        tabs={[
          { id: 'items', label: 'Partidas', count: taskItems.length },
          { id: 'timeline', label: 'Línea de tiempo', count: taskEvents.length },
        ]}
      />
      <TabPanel idPrefix={TAB_PREFIX} id={filters.view} className={styles.panel}>
        {filters.view === 'items' ? (
          <ItemsView data={data} items={taskItems} filters={filters} update={update} nodeFilter={nodeFilter} />
        ) : (
          <EventFeed data={data} filters={filters} update={update} search={<SearchBox value={filters.q} onChange={(q) => update({ q })} />} />
        )}
      </TabPanel>
    </>
  )
}

export function SearchBox({ value, onChange, placeholder = 'Buscar' }: { value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <label className={styles.search}>
      <Search aria-hidden />
      <input type="search" value={value} placeholder={placeholder} aria-label={placeholder} onChange={(e) => onChange(e.target.value)} />
    </label>
  )
}

// ---------------------------------------------------------------- items list
const GROUPS = [
  { value: 'tarea', label: 'Tarea' },
  { value: 'estado', label: 'Estado' },
  { value: 'sociedad', label: 'Sociedad' },
  { value: 'resultado', label: 'Resultado' },
]

const SORTS = [
  { value: 'key', label: 'Partida' },
  { value: 'amount', label: 'Importe' },
  { value: 'company', label: 'Sociedad' },
  { value: 'confidence', label: 'Confianza' },
]

interface ItemsViewProps extends ActivityProps {
  items: WorkItem[]
  nodeFilter: FlowFilter | null
}

function ItemsView({ data, items, filters, update, nodeFilter }: ItemsViewProps) {
  const openItem = useOpenItem()
  const activeItemId = useActiveItemId()
  const [sort, setSort] = useState<SortState | null>(null)
  const [cursor, setCursor] = useState<string | null>(null)
  const attention = useMemo(() => new Set(data.attention.map((a) => a.item)), [data.attention])
  const rows = useMemo(() => filterItems(items, filters, { attention, node: nodeFilter?.items ?? null }), [items, filters, attention, nodeFilter])
  const withTask = !filters.task

  const statusCounts = useMemo(() => countBy(items, (i) => i.status), [items])
  const companyCounts = useMemo(() => countBy(items, (i) => i.company ?? '—'), [items])
  const outcomeCounts = useMemo(() => countBy(items, outcomeKey), [items])
  const attentionCount = useMemo(() => items.filter((i) => attention.has(i.id)).length, [items, attention])

  const columns = useMemo<Column<WorkItem>[]>(
    () => [
      { id: 'status', header: '', width: 28, cell: (r) => <StatusDot status={r.status} label={ITEM_STATUS[r.status].label} />, sortValue: (r) => ITEM_STATUS_ORDER.indexOf(r.status) },
      ...(withTask ? [{ id: 'task', header: 'Tarea', width: 104, cell: (r: WorkItem) => <span className={styles.task}>{taskLabel(r.task)}</span>, sortValue: (r: WorkItem) => TASK_KEYS.indexOf(r.task) }] : []),
      { id: 'key', header: 'Partida', width: 188, cell: (r) => <Mono className={styles.ellipsis}>{r.key}</Mono>, sortValue: (r) => r.key },
      { id: 'title', header: 'Descripción', width: 'minmax(220px, 2fr)', cell: (r) => <span className={styles.ellipsis}>{r.title}</span> },
      { id: 'counterparty', header: 'Contraparte', width: 'minmax(140px, 1fr)', cell: (r) => <span className={styles.ellipsis}>{r.counterparty ?? '—'}</span>, sortValue: (r) => r.counterparty },
      { id: 'company', header: 'Soc.', width: 64, cell: (r) => <Mono muted>{r.company ?? '—'}</Mono>, sortValue: (r) => r.company },
      { id: 'amount', header: 'Importe', width: 128, align: 'right', cell: (r) => <Amount cents={r.amount} currency={r.currency ?? 'EUR'} />, sortValue: (r) => (r.amount === null ? null : Math.abs(r.amount)) },
      {
        id: 'outcome',
        header: 'Resultado',
        width: 196,
        cell: (r) => (
          <Badge tone={ITEM_STATUS[r.status].tone} variant="outline" className={styles.outcome}>
            {outcomeLabel(outcomeKey(r), false, taskLabel)}
          </Badge>
        ),
        sortValue: (r) => outcomeKey(r),
      },
      { id: 'provenance', header: 'Origen', width: 56, cell: (r) => <ProvenanceBadge provenance={r.provenance} compact /> },
      { id: 'confidence', header: 'Confianza', width: 92, cell: (r) => <ConfidenceBand value={r.confidence} />, sortValue: (r) => r.confidence },
    ],
    [withTask],
  )

  const group = GROUPS.some((g) => g.value === filters.group) ? filters.group : null
  const groupBy = useMemo(() => {
    switch (group) {
      case 'tarea':
        return (r: WorkItem) => r.task
      case 'estado':
        return (r: WorkItem) => r.status
      case 'sociedad':
        return (r: WorkItem) => r.company ?? '—'
      case 'resultado':
        return outcomeKey
      default:
        return undefined
    }
  }, [group])
  const groupOrder = group === 'tarea' ? [...TASK_KEYS] : group === 'estado' ? ITEM_STATUS_ORDER : undefined
  const renderGroup = useCallback(
    (key: string) => {
      if (group === 'tarea') return taskLabel(key as TaskKey)
      if (group === 'estado') return ITEM_STATUS[key as keyof typeof ITEM_STATUS]?.label ?? key
      if (group === 'resultado') return outcomeLabel(key, withTask, taskLabel)
      return key
    },
    [group, withTask],
  )

  const active = filters.status.length + filters.company.length + filters.outcome.length + (filters.attention ? 1 : 0) + (filters.q ? 1 : 0) + (filters.node ? 1 : 0) > 0

  return (
    <div className={styles.list}>
      <FilterBar
        onClear={active ? () => update(CLEARED) : undefined}
        end={
          <>
            <span className={styles.count}>
              {formatNumber(rows.length)} de {formatNumber(items.length)} partidas
            </span>
            <ViewOptions
              groupBy={{ options: GROUPS, value: group, onChange: (g) => update({ group: g }) }}
              sort={{ options: SORTS, value: sort, onChange: setSort }}
            />
          </>
        }
      >
        <SearchBox value={filters.q} onChange={(q) => update({ q })} placeholder="Buscar partida, contraparte…" />
        {nodeFilter && (
          <Pill tone="brand" onRemove={() => update({ node: null })} removeLabel="Quitar filtro del mapa">
            Mapa: {nodeFilter.label}
          </Pill>
        )}
        <FilterChip
          label="Estado"
          options={ITEM_STATUS_ORDER.filter((s) => statusCounts.has(s)).map((s) => ({ value: s, label: ITEM_STATUS[s].label, count: statusCounts.get(s) }))}
          selected={filters.status}
          onChange={(status) => update({ status })}
        />
        <FilterChip
          label="Sociedad"
          options={[...companyCounts].sort((a, b) => a[0].localeCompare(b[0])).map(([c, n]) => ({ value: c, label: c, count: n }))}
          selected={filters.company}
          onChange={(company) => update({ company })}
        />
        <FilterChip
          label="Resultado"
          options={[...outcomeCounts].sort((a, b) => b[1] - a[1]).map(([k, n]) => ({ value: k, label: outcomeLabel(k, withTask, taskLabel), count: n }))}
          selected={filters.outcome}
          onChange={(outcome) => update({ outcome })}
        />
        <FilterChip
          label="Atención"
          options={[
            { value: 'yes', label: 'Con atención', count: attentionCount },
            { value: 'no', label: 'Sin atención', count: items.length - attentionCount },
          ]}
          selected={filters.attention ? [filters.attention] : []}
          onChange={(v) => update({ attention: (v.length === 1 ? v[0] : v.length === 2 ? v[v.length - 1] : null) as ActivityFilters['attention'] })}
        />
      </FilterBar>
      <DataTable
        aria-label="Partidas"
        rows={rows}
        columns={columns}
        getRowId={getId}
        sort={sort}
        onSortChange={setSort}
        groupBy={groupBy}
        groupOrder={groupOrder}
        renderGroup={renderGroup}
        selectedId={activeItemId ?? cursor}
        onSelectedChange={(id) => {
          setCursor(id)
          if (id && activeItemId) openItem(id)
        }}
        onOpen={(r) => openItem(r.id)}
        globalKeys
      />
    </div>
  )
}

const getId = (r: WorkItem) => r.id
