// /atencion — what the agent could not close alone, grouped by who has to act and by priority.
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { CheckCheck, ChevronDown, ChevronRight, CircleHelp, Download, Globe, Info, ListTree, Search, SearchX, ShieldAlert, StickyNote, Undo2 } from 'lucide-react'
import {
  Amount,
  Button,
  EmptyState,
  FilterBar,
  FilterChip,
  IconButton,
  Mono,
  Page,
  PageHeader,
  PRIORITY,
  PriorityBadge,
  QueryState,
  Section,
  SegmentedControl,
  Tooltip,
  toast,
  type FilterOption,
} from '@/components'
import { ATTENTION_KINDS, TASK_KEYS, type DerivedRun } from '@/domain/types'
import { useDerivedRun } from '@/engine'
import { formatDateTime, formatNumber } from '@/lib/format'
import { shouldIgnoreHotkey } from '@/lib/keyboard'
import { PageActions } from '@/shell/PageActions'
import { useActiveItemId, useOpenItem } from '@/shell/useOpenItem'
import { TASK_LABEL } from '@/domain/catalog/labels'
import { AttentionCard, type RowActions } from './AttentionCard'
import { NoteDialog, SimilarDialog } from './AttentionDialogs'
import {
  NO_FILTERS,
  PRIORITIES,
  attentionIdOf,
  buildRows,
  decisionLabel,
  groupByPriority,
  hasFilters,
  kindLabel,
  matchesFilters,
  overrideFor,
  rowKeyLabel,
  similarRows,
  totalsByCurrency,
  type AttentionFilters,
  type AttentionRow,
  type Family,
} from './attentionModel'
import { useOverridesStore, type Override, type OverrideAction } from './overridesStore'
import { Totals } from './Totals'
import styles from './AttentionPage.module.css'

const SUBTITLE = 'Lo que el agente no puede cerrar solo: excepciones de política, dudas y estimaciones.'

const FAMILY_META: Record<Family, { title: string; description: string; icon: ReactNode }> = {
  fraud: {
    title: 'Posible fraude',
    description: 'Siempre primero y aparte: no se paga nada hasta confirmarlo fuera del sistema.',
    icon: <ShieldAlert aria-hidden className={styles.fraudIcon} />,
  },
  world: {
    title: 'El mundo necesita una acción',
    description: 'El agente está seguro de su decisión, pero alguien tiene que actuar fuera: pedir una factura nueva, llamar al proveedor, dar de alta un maestro.',
    icon: <Globe aria-hidden />,
  },
  doubt: {
    title: 'El agente duda',
    description: 'Estimaciones, diferencias sin explicar y datos dudosos: revisa la recomendación y sus alternativas antes de aceptar.',
    icon: <CircleHelp aria-hidden />,
  },
}

type FamilyView = 'all' | 'world' | 'doubt'

const NO_OVERRIDES: Override[] = []

export default function AttentionPage() {
  const { data, status, error } = useDerivedRun()
  if (!data) {
    return (
      <Page>
        <PageHeader title="Atención" subtitle={SUBTITLE} />
        <QueryState status={status} error={error}>
          {null}
        </QueryState>
      </Page>
    )
  }
  return <AttentionQueue key={data.runId} run={data} />
}

function AttentionQueue({ run }: { run: DerivedRun }) {
  const runId = run.runId
  const overrides = useOverridesStore((s) => s.byRun[runId] ?? NO_OVERRIDES)
  const add = useOverridesStore((s) => s.add)
  const remove = useOverridesStore((s) => s.remove)
  const openItem = useOpenItem()
  const peekOpen = useActiveItemId() != null

  const [filters, setFilters] = useState<AttentionFilters>(NO_FILTERS)
  const [view, setView] = useState<FamilyView>('all')
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(true)
  const [noteKey, setNoteKey] = useState<string | null>(null)
  const [similarFor, setSimilarFor] = useState<AttentionRow[] | null>(null)
  const listRef = useRef<HTMLDivElement>(null)

  const rows = useMemo(() => buildRows(run.attention, run.itemsById, overrides), [run, overrides])
  const pendingAll = useMemo(() => rows.filter((r) => r.resolution === 'pending'), [rows])
  const visible = useMemo(() => rows.filter((r) => matchesFilters(r, filters)), [rows, filters])
  const pending = visible.filter((r) => r.resolution === 'pending')
  const snoozed = visible.filter((r) => r.resolution === 'snoozed')
  const resolved = visible.filter((r) => r.resolution === 'resolved')
  const resolvedCount = rows.filter((r) => r.resolution === 'resolved').length

  const sections = (['fraud', 'world', 'doubt'] as Family[])
    .filter((f) => f === 'fraud' || view === 'all' || view === f)
    .map((family) => ({ family, rows: pending.filter((r) => r.family === family) }))
    .filter((s) => s.rows.length > 0)
    .map((s) => ({ ...s, groups: groupByPriority(s.rows) }))
  const ordered = sections.flatMap((s) => s.groups.flatMap((g) => g.rows))
  const selected = ordered.find((r) => r.key === selectedKey) ?? null
  const similarCount = useMemo(() => (selected ? similarRows(selected, rows).length : 0), [selected, rows])

  // ------------------------------------------------------------ actions
  const focusRow = (r: AttentionRow | null) => {
    setSelectedKey(r?.key ?? null)
    setExpanded(true)
    if (r && peekOpen) openItem(r.a.item)
  }

  const move = (delta: 1 | -1) => {
    if (ordered.length === 0) return
    const i = selected ? ordered.indexOf(selected) : -1
    const next = i === -1 ? (delta === 1 ? 0 : ordered.length - 1) : Math.min(Math.max(i + delta, 0), ordered.length - 1)
    focusRow(ordered[next])
  }

  /** When the selected row leaves the queue, the cursor goes to the next one still pending. */
  const moveOn = (leaving: AttentionRow[]) => {
    if (!selected) return
    const gone = new Set(leaving.map((r) => r.key))
    if (!gone.has(selected.key)) return
    const i = ordered.indexOf(selected)
    const stays = (r: AttentionRow) => !gone.has(r.key)
    focusRow(ordered.slice(i + 1).find(stays) ?? ordered.slice(0, i).reverse().find(stays) ?? null)
  }

  const target = (r: AttentionRow) => ({ runId, item: r.a.item, attention_id: attentionIdOf(r.a) })

  /** Back to pending; a saved note stays. */
  const reopen = (list: AttentionRow[]) => {
    const current = useOverridesStore.getState().forRun(runId)
    for (const r of list) {
      if (overrideFor(current, r.a)?.note) add({ ...target(r), action: 'NOTE', decision: null })
      else remove(runId, r.a.item, attentionIdOf(r.a))
    }
  }

  const resolve = (list: AttentionRow[], action: OverrideAction, decision: (r: AttentionRow) => string | null, message: string) => {
    moveOn(list)
    for (const r of list) add({ ...target(r), action, decision: decision(r) })
    toast(message, { tone: 'ok', action: { label: 'Deshacer', onClick: () => reopen(list) } })
  }

  const recommended = (r: AttentionRow) => r.a.recommendation?.decision ?? null

  const actions: RowActions = {
    select: (r) => (r.key === selectedKey ? setExpanded((e) => !e) : focusRow(r)),
    accept: (r) => resolve([r], 'ACCEPT', recommended, 'Recomendación aceptada'),
    choose: (r, decision) => resolve([r], 'CHOOSE_ALTERNATIVE', () => decision, `Alternativa elegida: ${decisionLabel(r.task, decision)}`),
    snooze: (r) => resolve([r], 'SNOOZE', () => null, 'Pospuesta'),
    note: (r) => setNoteKey(r.key),
    open: (r) => {
      setSelectedKey(r.key)
      openItem(r.a.item)
    },
    similar: (r) => setSimilarFor([r, ...similarRows(r, rows)]),
  }

  const saveNote = (r: AttentionRow, note: string) => {
    setNoteKey(null)
    if (note) add({ ...target(r), action: r.override?.action ?? 'NOTE', decision: r.override?.decision ?? null, note })
    else if (r.override?.action === 'NOTE') remove(runId, r.a.item, attentionIdOf(r.a))
    else if (r.override) add({ ...target(r), action: r.override.action, decision: r.override.decision, note: null })
    toast.success(note ? 'Nota guardada' : 'Nota borrada')
  }

  const acceptSimilar = (list: AttentionRow[]) => {
    setSimilarFor(null)
    resolve(list, 'ACCEPT', recommended, `${formatNumber(list.length)} partidas aceptadas`)
  }

  const exportOverrides = () => {
    const text = useOverridesStore.getState().toJsonl(runId)
    downloadText('overrides.jsonl', text ? `${text}\n` : '')
    toast.success('overrides.jsonl descargado', { description: 'Las correcciones van aparte: los 6 ficheros entregados no cambian.' })
  }

  // ------------------------------------------------------------ keyboard: j/k, Enter, a, p, n
  const onKey = (e: KeyboardEvent) => {
    if (shouldIgnoreHotkey(e) || e.shiftKey) return
    const inList = e.target === document.body || (e.target instanceof Node && !!listRef.current?.contains(e.target))
    if (e.key === 'j' || e.key === 'k' || (inList && (e.key === 'ArrowDown' || e.key === 'ArrowUp'))) {
      e.preventDefault()
      move(e.key === 'j' || e.key === 'ArrowDown' ? 1 : -1)
      return
    }
    if (!selected) return
    const onControl = e.target instanceof Element && e.target.closest('button, a, input, textarea, select, [role="menuitem"]')
    if (e.key === 'Enter' && !onControl) actions.open(selected)
    else if (e.key === 'a') actions.accept(selected)
    else if (e.key === 'p') actions.snooze(selected)
    else if (e.key === 'n') actions.note(selected)
    else return
    e.preventDefault()
  }
  const onKeyRef = useRef(onKey)
  useEffect(() => {
    onKeyRef.current = onKey
  })
  useEffect(() => {
    const listener = (e: KeyboardEvent) => onKeyRef.current(e)
    window.addEventListener('keydown', listener)
    return () => window.removeEventListener('keydown', listener)
  }, [])

  useEffect(() => {
    if (!selectedKey) return
    listRef.current?.querySelector(`[data-key="${CSS.escape(selectedKey)}"]`)?.scrollIntoView({ block: 'nearest' })
  }, [selectedKey, expanded])

  // ------------------------------------------------------------ filters
  const facets = useMemo(() => {
    const count = (get: (r: AttentionRow) => string | null | undefined) => {
      const m = new Map<string, number>()
      for (const r of pendingAll) {
        const v = get(r)
        if (v) m.set(v, (m.get(v) ?? 0) + 1)
      }
      return m
    }
    const options = (counts: Map<string, number>, order: readonly string[], label: (v: string) => string): FilterOption[] =>
      order.filter((v) => counts.has(v)).map((v) => ({ value: v, label: label(v), count: counts.get(v) }))
    const companies = count((r) => r.item?.company)
    return {
      priority: options(count((r) => r.a.priority), PRIORITIES, (p) => `${p} · ${PRIORITY[p as keyof typeof PRIORITY].description}`),
      kind: options(count((r) => r.a.kind), ATTENTION_KINDS, (k) => kindLabel(k as (typeof ATTENTION_KINDS)[number])),
      task: options(count((r) => r.task), TASK_KEYS, (t) => TASK_LABEL[t as keyof typeof TASK_LABEL]),
      company: options(companies, [...companies.keys()].sort(), (c) => c),
    }
  }, [pendingAll])

  const setFacet = (key: keyof Omit<AttentionFilters, 'query'>) => (next: string[]) => setFilters((f) => ({ ...f, [key]: next }))
  const filtered = hasFilters(filters)
  const clearAll = () => {
    setFilters(NO_FILTERS)
    setView('all')
  }
  const familyCount = (f: Family) => pending.filter((r) => r.family === f).length

  return (
    <Page>
      <PageActions>
        <Button leadingIcon={<Download aria-hidden />} onClick={exportOverrides} disabled={overrides.length === 0}>
          Exportar correcciones (overrides.jsonl)
        </Button>
      </PageActions>
      <PageHeader
        title="Atención"
        subtitle={SUBTITLE}
        actions={
          <div className={styles.counters}>
            <span>
              Quedan <strong className="tabular">{formatNumber(pendingAll.length)}</strong>
              {pendingAll.length > 0 && (
                <>
                  {' · '}
                  <Totals totals={totalsByCurrency(pendingAll)} compact />
                </>
              )}
            </span>
            <span className={styles.counterSep} aria-hidden />
            <span>
              Resueltas <strong className="tabular">{formatNumber(resolvedCount)}</strong>
            </span>
          </div>
        }
        filters={
          <div className={styles.filterRow}>
            <SegmentedControl
              aria-label="Familia"
              size="sm"
              value={view}
              onChange={setView}
              options={[
                { value: 'all', label: 'Todas' },
                { value: 'world', label: <>Necesita una acción<span className={styles.segCount}>{familyCount('world')}</span></> },
                { value: 'doubt', label: <>El agente duda<span className={styles.segCount}>{familyCount('doubt')}</span></> },
              ]}
            />
            <FilterBar
              className={styles.filterBar}
              onClear={filtered ? () => setFilters(NO_FILTERS) : undefined}
              end={
                <>
                  <label className={styles.search}>
                    <Search aria-hidden />
                    <input
                      type="search"
                      value={filters.query}
                      onChange={(e) => setFilters((f) => ({ ...f, query: e.target.value }))}
                      onKeyDown={(e) => e.key === 'Escape' && e.currentTarget.blur()}
                      placeholder="Buscar partida, título o contraparte…"
                      aria-label="Buscar en Atención"
                    />
                  </label>
                  <span className={styles.resultCount}>{formatNumber(ordered.length)} pendientes</span>
                </>
              }
            >
              <FilterChip label="Prioridad" options={facets.priority} selected={filters.priority} onChange={setFacet('priority')} />
              <FilterChip label="Tipo" options={facets.kind} selected={filters.kind} onChange={setFacet('kind')} />
              <FilterChip label="Tarea" options={facets.task} selected={filters.task} onChange={setFacet('task')} />
              <FilterChip label="Sociedad" options={facets.company} selected={filters.company} onChange={setFacet('company')} />
            </FilterBar>
          </div>
        }
      />

      <div ref={listRef} className={styles.queue}>
        {sections.map((s) => {
          const meta = FAMILY_META[s.family]
          return (
            <Section
              key={s.family}
              title={
                <span className={styles.familyTitle}>
                  {meta.icon}
                  {meta.title}
                </span>
              }
              description={meta.description}
              count={s.rows.length}
            >
              <div className={styles.list} aria-label={meta.title}>
                {s.groups.map((g) => (
                  <div key={g.priority} className={styles.group}>
                    <div className={styles.groupHeader}>
                      <PriorityBadge priority={g.priority} />
                      <span className={styles.groupLabel}>{PRIORITY[g.priority].description}</span>
                      <span className={styles.count}>{formatNumber(g.rows.length)}</span>
                      <span className={styles.groupTotals}>
                        <Totals totals={g.totals} compact />
                      </span>
                    </div>
                    {g.rows.map((r) => (
                      <AttentionCard
                        key={r.key}
                        row={r}
                        selected={r.key === selectedKey}
                        expanded={expanded}
                        similarCount={r.key === selectedKey ? similarCount : 0}
                        actions={actions}
                      />
                    ))}
                  </div>
                ))}
              </div>
            </Section>
          )
        })}

        {ordered.length === 0 &&
          (pendingAll.length === 0 ? (
            <EmptyState
              icon={<CheckCheck />}
              title="Nada pendiente"
              description={
                rows.length === 0
                  ? 'El agente no ha dejado nada para una persona en esta ejecución.'
                  : 'Has revisado todo lo que el agente dejó para una persona.'
              }
            />
          ) : (
            <EmptyState
              icon={<SearchX />}
              title="Sin resultados"
              description="No queda nada pendiente con estos filtros."
              action={<Button onClick={clearAll}>Limpiar filtros</Button>}
            />
          ))}

        <ClosedList title="Pospuestas" rows={snoozed} undoLabel="Reactivar" onUndo={(r) => reopen([r])} onOpen={actions.open} />
        <ClosedList title="Resueltas" rows={resolved} undoLabel="Deshacer" onUndo={(r) => reopen([r])} onOpen={actions.open} />

        <p className={styles.footnote}>
          <Info aria-hidden />
          Tus decisiones se guardan en este navegador y se exportan aparte en overrides.jsonl. No cambian los ficheros entregados: el trabajo lo hace el agente.
        </p>
      </div>

      <NoteDialog row={rows.find((r) => r.key === noteKey) ?? null} onClose={() => setNoteKey(null)} onSave={saveNote} />
      <SimilarDialog rows={similarFor} onClose={() => setSimilarFor(null)} onConfirm={acceptSimilar} />
    </Page>
  )
}

function outcomeText(r: AttentionRow): string {
  const o = r.override
  if (!o) return ''
  if (o.action === 'SNOOZE') return 'Pospuesta'
  const label = o.decision ? decisionLabel(r.task, o.decision) : 'sin decisión'
  return o.action === 'CHOOSE_ALTERNATIVE' ? `Alternativa · ${label}` : `Aceptada · ${label}`
}

interface ClosedListProps {
  title: string
  rows: AttentionRow[]
  undoLabel: string
  onUndo: (r: AttentionRow) => void
  onOpen: (r: AttentionRow) => void
}

/** Collapsed list of entries that left the queue, each with its decision and an undo. */
function ClosedList({ title, rows, undoLabel, onUndo, onOpen }: ClosedListProps) {
  const [open, setOpen] = useState(false)
  if (rows.length === 0) return null
  return (
    <section className={styles.closed}>
      <button type="button" className={styles.closedHeader} aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? <ChevronDown aria-hidden /> : <ChevronRight aria-hidden />}
        {title}
        <span className={styles.count}>{formatNumber(rows.length)}</span>
        <span className={styles.closedTotals}>
          <Totals totals={totalsByCurrency(rows)} compact />
        </span>
      </button>
      {open && (
        <div className={styles.list}>
          {rows.map((r) => (
            <div key={r.key} className={styles.closedRow}>
              <Mono className={styles.key}>{rowKeyLabel(r)}</Mono>
              <span className={styles.titleCell}>
                <span className={styles.title}>{r.a.title}</span>
                {r.item?.counterparty && <span className={styles.counterparty}>{r.item.counterparty}</span>}
              </span>
              <span className={styles.outcome}>
                {outcomeText(r)}
                {r.override?.note && (
                  <Tooltip content={r.override.note}>
                    <span className={styles.noteWrap} tabIndex={0} aria-label={`Nota: ${r.override.note}`}>
                      <StickyNote aria-hidden className={styles.noteIcon} />
                    </span>
                  </Tooltip>
                )}
              </span>
              <span className={styles.when}>{formatDateTime(r.override?.ts)}</span>
              <Amount className={styles.amount} cents={r.a.impact} currency={r.item?.currency ?? 'EUR'} />
              <span className={styles.rowButtons}>
                <IconButton icon={<ListTree />} label="Ver razonamiento" size="sm" onClick={() => onOpen(r)} />
                <Button size="sm" variant="ghost" leadingIcon={<Undo2 aria-hidden />} onClick={() => onUndo(r)}>
                  {undoLabel}
                </Button>
              </span>
            </div>
          ))}
        </div>
      )}
    </section>
  )
}

function downloadText(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/x-ndjson' }))
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 0)
}
