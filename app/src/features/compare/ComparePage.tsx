// Comparar con golden: sub-scores per task down to the item, and the field-by-field differences.
import { useCallback, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router'
import { CircleCheck, GitCompareArrows, MousePointerClick } from 'lucide-react'
import type { DerivedRun, ScoreReport, TaskKey } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { TASK_META } from '@/domain/catalog/labels'
import {
  Badge,
  Button,
  ButtonLink,
  DataTable,
  EmptyState,
  FilterBar,
  Mono,
  Page,
  PageHeader,
  Pill,
  QueryState,
  SegmentedControl,
  Tooltip,
  type Column,
  type SortState,
  type Tone,
} from '@/components'
import { useDerivedRun } from '@/engine'
import { useActiveItemId, useCloseItem, useOpenItem } from '@/shell/useOpenItem'
import { formatNumber, formatPercent } from '@/lib/format'
import { diffLabel, GoldenDiff } from '@/features/item/kit'
import { applyCompareParams, diffRows, parseCompareParams, taskSummaries, type CompareParams, type CompareView, type DiffKind, type DiffRow } from './model'
import { TaskScores } from './TaskScores'
import styles from './ComparePage.module.css'

const VIEWS: { value: CompareView; label: string }[] = [
  { value: 'diff', label: 'Solo diferencias' },
  { value: 'all', label: 'Todo' },
]

const KIND: Record<DiffKind, { label: string; tone: Tone }> = {
  missing: { label: 'No entregada', tone: 'danger' },
  extra: { label: 'No está en golden', tone: 'warn' },
  different: { label: 'Difiere', tone: 'warn' },
  exact: { label: 'Exacta', tone: 'ok' },
  inherited: { label: 'Pierde por sus partidas', tone: 'neutral' },
}

export default function ComparePage() {
  const { data, status, error } = useDerivedRun()
  const [searchParams, setSearchParams] = useSearchParams()
  const params = useMemo(() => parseCompareParams(searchParams), [searchParams])
  const update = useCallback(
    (patch: Partial<CompareParams>) => setSearchParams((prev) => applyCompareParams(prev, patch), { replace: true, preventScrollReset: true }),
    [setSearchParams],
  )

  return (
    <Page fill>
      <PageHeader
        title="Comparar con golden"
        subtitle="En qué se equivoca el agente: cada partida que difiere de la referencia, ordenada por la nota que pierde."
        actions={<SegmentedControl aria-label="Comparar" size="sm" options={VIEWS} value={params.view} onChange={(view) => update({ view })} />}
      />
      <QueryState status={status} error={error}>
        {() =>
          data &&
          (data.score ? (
            <Compare data={data} score={data.score} params={params} update={update} />
          ) : (
            <EmptyState
              icon={<GitCompareArrows />}
              title="Sin referencia con la que comparar"
              description="La comparación necesita la solución golden del dataset, y solo la trae julio (fase dev). Abre una ejecución sobre ese dataset."
              action={<ButtonLink to="/ejecuciones">Ver ejecuciones</ButtonLink>}
            />
          ))
        }
      </QueryState>
    </Page>
  )
}

interface CompareProps {
  data: DerivedRun
  score: ScoreReport
  params: CompareParams
  update: (patch: Partial<CompareParams>) => void
}

const getId = (r: DiffRow) => r.id
const taskLabel = (t: TaskKey) => TASK_META[t].label

function Compare({ data, score, params, update }: CompareProps) {
  const openItem = useOpenItem()
  const closeItem = useCloseItem()
  const activeItemId = useActiveItemId()
  const [cursor, setCursor] = useState<string | null>(null)
  const [sort, setSort] = useState<SortState | null>(null)

  const summaries = useMemo(() => taskSummaries(score), [score])
  const rows = useMemo(() => diffRows(score.perItem, { all: params.view === 'all', task: params.task }), [score, params.view, params.task])
  const differing = useMemo(() => (params.task ? (summaries.find((s) => s.task === params.task)?.differing ?? 0) : summaries.reduce((n, s) => n + (s.differing ?? 0), 0)), [summaries, params.task])

  const pick = (id: string | null) => (id && rows.some((r) => r.id === id) ? id : null)
  const current = pick(activeItemId) ?? pick(cursor) ?? rows[0]?.id ?? null
  const currentRow = rows.find((r) => r.id === current) ?? null

  // Items the run does not have (not delivered, or account-level bank entries) have no peek: their diff is shown here.
  const open = (id: string) => {
    if (data.itemsById.has(id)) openItem(id, 'golden')
    else if (activeItemId) closeItem()
  }

  const withTask = !params.task
  const columns = useMemo<Column<DiffRow>[]>(
    () => [
      {
        id: 'kind',
        header: 'Resultado',
        width: 120,
        cell: (r) => (
          <Badge tone={KIND[r.kind].tone} variant="outline">
            {KIND[r.kind].label}
          </Badge>
        ),
        sortValue: (r) => r.kind,
      },
      ...(withTask ? [{ id: 'task', header: 'Tarea', width: 96, cell: (r: DiffRow) => <span className={styles.task}>{taskLabel(r.task)}</span>, sortValue: (r: DiffRow) => TASK_KEYS.indexOf(r.task) }] : []),
      { id: 'key', header: 'Partida', width: 'minmax(140px, 1fr)', cell: (r) => <Mono className={styles.ellipsis}>{r.key}</Mono>, sortValue: (r) => r.key },
      { id: 'paths', header: 'Qué difiere', width: 'minmax(120px, 1.2fr)', cell: (r) => <span className={styles.ellipsis}>{r.paths.length ? r.paths.map(diffLabel).join(', ') : '—'}</span> },
      { id: 'score', header: 'Nota', width: 64, align: 'right', cell: (r) => <span className="tabular">{formatPercent(r.score, { decimals: 0 })}</span>, sortValue: (r) => r.score },
      { id: 'diffs', header: 'Dif.', width: 56, align: 'right', cell: (r) => <span className="tabular">{r.diffs || '—'}</span>, sortValue: (r) => r.diffs },
      {
        id: 'loss',
        header: (
          <Tooltip content="Puntos de la nota total que cuesta la partida: peso de la tarea × (1 − nota de la partida) ÷ partidas de la tarea en golden. Aproximado en las tareas que se puntúan con F1.">
            <span>Pierde</span>
          </Tooltip>
        ),
        width: 80,
        align: 'right',
        cell: (r) => <span className="tabular">{!r.loss ? '—' : r.loss < 0.01 ? `< ${formatNumber(0.01, { decimals: 2 })}` : formatNumber(r.loss, { decimals: 2 })}</span>,
        sortValue: (r) => r.loss,
      },
    ],
    [withTask],
  )

  return (
    <>
      <TaskScores total={score.total} summaries={summaries} selected={params.task} onSelect={(task) => update({ task })} />
      <div className={styles.body}>
        <div className={styles.list}>
          <FilterBar
            end={
              <span className={styles.count}>
                {params.view === 'all' ? `${formatNumber(rows.length)} partidas · ${formatNumber(differing)} ${differing === 1 ? 'difiere' : 'difieren'}` : `${formatNumber(rows.length)} ${rows.length === 1 ? 'partida difiere' : 'partidas difieren'}`}
              </span>
            }
          >
            {params.task ? (
              <Pill tone="brand" onRemove={() => update({ task: null })} removeLabel="Quitar filtro de tarea">
                Tarea: {taskLabel(params.task)}
              </Pill>
            ) : (
              <span className={styles.hint}>Pulsa una tarea para filtrar la lista.</span>
            )}
          </FilterBar>
          <DataTable
            aria-label="Partidas comparadas con golden"
            rows={rows}
            columns={columns}
            getRowId={getId}
            sort={sort}
            onSortChange={setSort}
            selectedId={current}
            onSelectedChange={(id) => {
              setCursor(id)
              if (id && activeItemId) open(id)
            }}
            onOpen={(r) => open(r.id)}
            globalKeys
            empty={<EmptyState size="sm" icon={<CircleCheck />} title="Sin diferencias con la referencia" description={params.task ? 'Esta tarea coincide con golden partida a partida.' : 'La entrega coincide con golden partida a partida.'} />}
          />
        </div>
        <aside className={styles.detail} aria-label="Diferencias de la partida">
          {currentRow ? (
            <DiffDetail row={currentRow} data={data} score={score} onOpen={() => openItem(currentRow.id, 'golden')} />
          ) : (
            <EmptyState size="sm" icon={<MousePointerClick />} title="Elige una partida" description="Verás sus diferencias con golden campo a campo." />
          )}
        </aside>
      </div>
    </>
  )
}

function DiffDetail({ row, data, score, onOpen }: { row: DiffRow; data: DerivedRun; score: ScoreReport; onOpen: () => void }) {
  const item = data.itemsById.get(row.id)
  return (
    <div className={styles.detailBody}>
      <header className={styles.detailHeader}>
        <div className={styles.detailTitle}>
          <Mono>{row.key}</Mono>
          <span className={styles.task}>{taskLabel(row.task)}</span>
          <Badge tone={KIND[row.kind].tone} variant="outline">
            {KIND[row.kind].label}
          </Badge>
        </div>
        {item && (
          <Button size="sm" variant="secondary" onClick={onOpen}>
            Abrir partida
          </Button>
        )}
      </header>
      {item ? <p className={styles.description}>{item.title}</p> : row.kind === 'missing' && <p className={styles.description}>La entrega no trae esta partida.</p>}
      <GoldenDiff score={score.perItem[row.id]} currency={item?.currency ?? 'EUR'} />
    </div>
  )
}
