import { useCallback, useMemo, useState, type ReactNode } from 'react'
import { Check, Circle, History, X } from 'lucide-react'
import type { AgentEvent, DerivedRun, EventKind, TaskKey } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { ConfidenceBand, DataTable, FilterBar, FilterChip, Mono, ViewOptions, type Column } from '@/components'
import { parseItemId } from '@/engine'
import { useActiveItemId, useOpenItem } from '@/shell/useOpenItem'
import { formatDateTime, formatNumber } from '@/lib/format'
import { EVENT_KIND_META, ModelChip, TASK_META } from '@/features/item/kit'
import { countBy, filterEvents, type ActivityFilters } from './activityModel'
import styles from './ActivityPage.module.css'

interface EventFeedProps {
  data: DerivedRun
  filters: ActivityFilters
  update: (patch: Partial<ActivityFilters>) => void
  search: ReactNode
}

const RESULTS = [
  { value: 'PASS', label: 'Correcto' },
  { value: 'FAIL', label: 'Falla' },
  { value: 'INFO', label: 'Información' },
]

const GROUPS = [
  { value: 'partida', label: 'Partida' },
  { value: 'paso', label: 'Tipo de paso' },
  { value: 'tarea', label: 'Tarea' },
]

const taskOf = (item: string): TaskKey | null => parseItemId(item)?.task ?? null

/** Chronological feed of every agent event (or the reconstructed trace) with filters by task, kind and result. */
export function EventFeed({ data, filters, update, search }: EventFeedProps) {
  const openItem = useOpenItem()
  const activeItemId = useActiveItemId()
  const [cursor, setCursor] = useState<string | null>(null)
  const scoped = useMemo(() => (filters.task ? data.events.filter((e) => taskOf(e.item) === filters.task) : data.events), [data.events, filters.task])
  const rows = useMemo(() => filterEvents(scoped, filters, taskOf), [scoped, filters])
  const kindCounts = useMemo(() => countBy(scoped, (e) => e.kind), [scoped])
  const resultCounts = useMemo(() => countBy(scoped, (e) => e.result), [scoped])
  const synthesized = data.eventsSynthesized
  const byEventId = useMemo(() => new Map(rows.map((e) => [getId(e), e])), [rows])

  const columns = useMemo<Column<AgentEvent>[]>(
    () => [
      {
        id: 'result',
        header: '',
        width: 28,
        cell: (e) => {
          const Icon = e.result === 'PASS' ? Check : e.result === 'FAIL' ? X : Circle
          return <Icon className={styles.result} data-result={e.result} aria-label={RESULTS.find((r) => r.value === e.result)?.label} />
        },
      },
      synthesized
        ? { id: 'when', header: 'Paso', width: 64, cell: (e) => <Mono muted>{e.seq}</Mono>, sortValue: (e) => e.seq }
        : { id: 'when', header: 'Hora', width: 150, cell: (e) => <span className={styles.muted}>{formatDateTime(e.ts)}</span>, sortValue: (e) => e.ts },
      {
        id: 'kind',
        header: 'Tipo',
        width: 140,
        cell: (e) => {
          const meta = EVENT_KIND_META[e.kind]
          const Icon = meta?.icon
          return (
            <span className={styles.kind}>
              {Icon && <Icon aria-hidden />}
              {meta?.label ?? e.kind}
            </span>
          )
        },
        sortValue: (e) => e.kind,
      },
      { id: 'item', header: 'Partida', width: 210, cell: (e) => <Mono className={styles.ellipsis}>{e.item}</Mono>, sortValue: (e) => e.item },
      { id: 'summary', header: 'Qué hizo', width: 'minmax(260px, 1fr)', cell: (e) => <span className={styles.ellipsis} title={e.summary}>{e.summary}</span> },
      { id: 'policy', header: 'Política', width: 80, cell: (e) => (e.policy_ref ? <Mono muted>{e.policy_ref}</Mono> : null), sortValue: (e) => e.policy_ref },
      {
        id: 'model',
        header: 'Modelo',
        width: 150,
        cell: (e) => (e.model ? <ModelChip model={e.model} /> : <ConfidenceBand value={e.confidence} />),
      },
    ],
    [synthesized],
  )

  const group = GROUPS.some((g) => g.value === filters.group) ? filters.group : null
  const groupBy = useMemo(() => {
    if (group === 'partida') return (e: AgentEvent) => e.item
    if (group === 'paso') return (e: AgentEvent) => e.kind
    if (group === 'tarea') return (e: AgentEvent) => taskOf(e.item) ?? '—'
    return undefined
  }, [group])
  const renderGroup = useCallback(
    (key: string) => {
      if (group === 'paso') return EVENT_KIND_META[key as EventKind]?.label ?? key
      if (group === 'tarea') return TASK_META[key as TaskKey]?.label ?? key
      return <Mono>{key}</Mono>
    },
    [group],
  )

  const active = filters.kind.length + filters.result.length + (filters.q ? 1 : 0) > 0
  return (
    <div className={styles.list}>
      {synthesized && (
        <p className={styles.notice}>
          <History aria-hidden />
          <span>
            <strong>Traza reconstruida desde la entrega.</strong> La ejecución no trae <Mono>trace/events.jsonl</Mono>: cada partida muestra los pasos que se deducen de su decisión,
            sus motivos y su asiento, sin horas ni duraciones reales.
          </span>
        </p>
      )}
      <FilterBar
        onClear={active ? () => update({ kind: [], result: [], q: '' }) : undefined}
        end={
          <>
            <span className={styles.count}>
              {formatNumber(rows.length)} de {formatNumber(scoped.length)} pasos
            </span>
            <ViewOptions groupBy={{ options: GROUPS, value: group, onChange: (g) => update({ group: g }) }} />
          </>
        }
      >
        {search}
        <FilterChip
          label="Tipo de paso"
          options={[...kindCounts].map(([k, n]) => ({ value: k, label: EVENT_KIND_META[k as EventKind]?.label ?? k, count: n }))}
          selected={filters.kind}
          onChange={(kind) => update({ kind })}
        />
        <FilterChip
          label="Resultado"
          options={RESULTS.filter((r) => resultCounts.has(r.value)).map((r) => ({ ...r, count: resultCounts.get(r.value) }))}
          selected={filters.result}
          onChange={(result) => update({ result })}
        />
      </FilterBar>
      <DataTable
        aria-label="Línea de tiempo"
        rows={rows}
        columns={columns}
        getRowId={getId}
        groupBy={groupBy}
        groupOrder={group === 'tarea' ? [...TASK_KEYS] : undefined}
        renderGroup={renderGroup}
        selectedId={cursor}
        onSelectedChange={(id) => {
          setCursor(id)
          const e = id ? byEventId.get(id) : undefined
          if (e && activeItemId) openItem(e.item)
        }}
        onOpen={(e) => openItem(e.item)}
        globalKeys
      />
    </div>
  )
}

const getId = (e: AgentEvent) => `${e.event_id}|${e.item}|${e.seq}`
