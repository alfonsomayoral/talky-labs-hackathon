// Ejecución: a backend run followed live over SSE (pipeline + event feed), or a stored run
// (golden, imported, finished API run) with its pipeline counts, manifest and real events.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { CircleX, SearchX } from 'lucide-react'
import { Badge, Button, ButtonLink, Card, EmptyState, Mono, Page, PageHeader, QueryState, statusSegments, StatusDot, toast } from '@/components'
import { sessionRestored, useDatasetStore, useRunStore } from '@/data/stores'
import type { AgentEvent, DerivedRun, RunBundle, TaskKey } from '@/domain/types'
import { useDerivedRun } from '@/engine'
import { formatDateTime, formatDuration, formatNumber } from '@/lib/format'
import { useOpenItem } from '@/shell/useOpenItem'
import { EventFeed } from './EventFeed'
import { createLiveTracker, taskTotals, type LiveSnapshot, type StreamState, type TaskProgress } from './live'
import { ManifestCard } from './ManifestCard'
import { NODE_STATE, PipelineDag, type DagNode } from './PipelineDag'
import { SourceBadge } from './SourceBadge'
import { filesPresent, PIPELINE, runPath } from './taskMeta'
import s from './RunLivePage.module.css'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const apiConfigured = Boolean(import.meta.env.VITE_API_URL)

const ROW_UNIT: Record<TaskKey, string> = {
  ap: 'documentos',
  ar_billing: 'partidas',
  bank_rec: 'cuentas',
  ar_cash: 'cobros',
  ic: 'diferencias',
  close: 'partidas de cierre',
}

const newestFirst = (a: AgentEvent, b: AgentEvent) => (b.ts ?? '').localeCompare(a.ts ?? '') || (b.seq ?? 0) - (a.seq ?? 0)
const shortItem = (id: string) => {
  const key = id.slice(id.indexOf(':') + 1)
  return key.length > 18 ? `${key.slice(0, 17)}…` : key
}

function useSessionReady(): boolean {
  const [ready, setReady] = useState(false)
  useEffect(() => {
    let alive = true
    void sessionRestored.finally(() => alive && setReady(true))
    return () => {
      alive = false
    }
  }, [])
  return ready
}

// ---------------------------------------------------------------- stored run

function storedNode(task: TaskKey, run: RunBundle, derived: DerivedRun | null): DagNode {
  if (!run.present[task]) return { task, state: 'pending', value: '—', caption: 'sin entrega', detail: 'Fichero ausente', progress: 0 }
  const timing = run.manifest?.tasks?.[task]
  const ms = timing?.started_at && timing.finished_at ? Date.parse(timing.finished_at) - Date.parse(timing.started_at) : NaN
  const duration = Number.isFinite(ms) ? formatDuration(ms) : null
  if (derived) {
    const t = derived.stats.byTask[task]
    const pending = t.needsHuman + t.blocked + t.open
    return {
      task,
      state: 'done',
      value: formatNumber(t.items),
      caption: 'partidas',
      segments: statusSegments({ AUTO: t.auto, NEEDS_HUMAN: t.needsHuman, BLOCKED: t.blocked, OPEN: t.open }),
      detail: duration ?? (pending ? `${formatNumber(pending)} sin resolver` : 'Todo resuelto'),
    }
  }
  return { task, state: 'done', value: formatNumber(run.deliverables[task].length), caption: ROW_UNIT[task], progress: 1, detail: duration ?? undefined }
}

function StoredRun({ run }: { run: RunBundle }) {
  const activeId = useRunStore((st) => st.activeId)
  const setActive = useRunStore((st) => st.setActive)
  const { data } = useDerivedRun()
  const openItem = useOpenItem()
  const isActive = activeId === run.id
  const derived = isActive && data?.runId === run.id ? data : null
  const nodes = PIPELINE.map((t) => storedNode(t, run, derived))
  const events = useMemo(() => (run.events ? [...run.events].sort(newestFirst) : null), [run.events])

  return (
    <Page>
      <PageHeader
        title={run.label}
        subtitle={
          <span className={s.subtitle}>
            <SourceBadge source={run.source} />
            <span>Creada {formatDateTime(run.createdAt)}</span>
            <span>· {filesPresent(run)} de 6 entregas</span>
            <Mono muted>· {run.id}</Mono>
          </span>
        }
        actions={
          isActive ? (
            <>
              <Badge tone="brand">Activa</Badge>
              <ButtonLink to="/entregables">Entregables</ButtonLink>
              <ButtonLink to="/" variant="primary">
                Ir al Resumen
              </ButtonLink>
            </>
          ) : (
            <Button
              variant="primary"
              onClick={() => {
                setActive(run.id)
                toast.success('Ejecución activa', { description: run.label })
              }}
            >
              Activar
            </Button>
          )
        }
      />

      <Card
        title="Tareas"
        description={derived ? 'Partidas por estado, en orden de ejecución. Pulsa una tarea para abrir su vista.' : 'Filas entregadas por tarea. Activa la ejecución para ver sus partidas por estado.'}
      >
        <PipelineDag nodes={nodes} />
      </Card>

      {run.manifest && <ManifestCard manifest={run.manifest} />}

      {events && (
        <Card title="Eventos del agente" description="trace/events.jsonl, del más reciente al más antiguo. Pulsa una partida para ver su razonamiento." padding="none">
          <EventFeed events={events} onOpenItem={openItem} />
        </Card>
      )}
    </Page>
  )
}

// ---------------------------------------------------------------- live API run

const STREAM: Record<StreamState, { label: string; tone: 'neutral' | 'info' | 'ok' | 'danger' }> = {
  connecting: { label: 'Conectando', tone: 'neutral' },
  running: { label: 'En curso', tone: 'info' },
  done: { label: 'Terminado', tone: 'ok' },
  failed: { label: 'Interrumpido', tone: 'danger' },
}

function liveNode(task: TaskKey, p: TaskProgress): DagNode {
  const unit = task === 'bank_rec' ? 'cuentas conciliadas' : 'partidas decididas'
  const detail = [p.state === 'running' && p.lastItem ? shortItem(p.lastItem) : NODE_STATE[p.state].label, p.fails ? (p.fails === 1 ? '1 fallo' : `${formatNumber(p.fails)} fallos`) : null]
    .filter(Boolean)
    .join(' · ')
  return {
    task,
    state: p.state,
    value: p.total !== null ? `${formatNumber(p.done)}/${formatNumber(p.total)}` : formatNumber(p.items),
    caption: p.total !== null ? unit : 'partidas',
    progress: p.total ? p.done / p.total : p.state === 'running' ? null : p.state === 'done' ? 1 : 0,
    detail,
  }
}

function LiveRun({ runId }: { runId: string }) {
  const navigate = useNavigate()
  const openItem = useOpenItem()
  const subscribeRun = useRunStore((st) => st.subscribeRun)
  const loadRemoteRun = useRunStore((st) => st.loadRemoteRun)
  const tasks = useDatasetStore((st) => st.api?.core.tasks ?? null)
  const initial = useMemo(() => createLiveTracker(taskTotals(tasks)).snapshot(), [tasks])
  const [snap, setSnap] = useState<LiveSnapshot | null>(null)
  const [attempt, setAttempt] = useState(0)
  const [result, setResult] = useState<{ state: 'loading' | 'error'; error?: string } | null>(null)

  const loadResult = useCallback(() => {
    setResult({ state: 'loading' })
    loadRemoteRun(`api:${runId}`).then(
      (run) => {
        toast.success('Cierre terminado', { description: `${run.label} · ${filesPresent(run)} de 6 entregas` })
        navigate(runPath(run.id), { replace: true })
      },
      (e: unknown) => setResult({ state: 'error', error: message(e) }),
    )
  }, [loadRemoteRun, navigate, runId])
  // The peek changes the URL (and navigate's identity); the stream must not reconnect for that.
  const loadResultRef = useRef(loadResult)
  useEffect(() => {
    loadResultRef.current = loadResult
  })

  useEffect(() => {
    const tracker = createLiveTracker(taskTotals(tasks))
    // Batch renders; a timer (not rAF) so a background tab keeps up too.
    let timer: ReturnType<typeof setTimeout> | undefined
    const flush = () => {
      timer = undefined
      setSnap(tracker.snapshot())
    }
    const unsubscribe = subscribeRun(runId, (e) => {
      tracker.push({ type: e.type, data: e.data })
      if (e.type === 'done') {
        clearTimeout(timer)
        flush()
        loadResultRef.current()
      } else timer ??= setTimeout(flush, 100)
    })
    return () => {
      unsubscribe()
      clearTimeout(timer)
    }
  }, [runId, subscribeRun, tasks, attempt])

  const view = snap ?? initial
  const stream = STREAM[view.state]
  return (
    <Page>
      <PageHeader
        title={view.state === 'done' ? 'Cierre terminado' : 'Cierre en curso'}
        subtitle={
          <span className={s.subtitle}>
            <StatusDot tone={stream.tone} pulse={view.state === 'running'} label="" />
            <span>{stream.label}</span>
            <span>· {formatNumber(view.received)} eventos</span>
            <Mono muted>· {runId}</Mono>
          </span>
        }
      />

      {view.state === 'failed' && (
        <div className={s.alert} role="alert">
          <CircleX aria-hidden />
          <span>{view.error}</span>
          <Button size="sm" onClick={() => setAttempt((n) => n + 1)}>
            Reconectar
          </Button>
        </div>
      )}
      {result?.state === 'loading' && <div className={s.note}>Cargando las entregas del backend…</div>}
      {result?.state === 'error' && (
        <div className={s.alert} role="alert">
          <CircleX aria-hidden />
          <span>No se pudieron cargar los resultados: {result.error}</span>
          <Button size="sm" onClick={loadResult}>
            Reintentar
          </Button>
        </div>
      )}

      <Card title="Tareas" description="Progreso por tarea en orden de ejecución. Pulsa una tarea para abrir su vista.">
        <PipelineDag nodes={PIPELINE.map((t) => liveNode(t, view.tasks[t]))} label="Progreso del cierre" />
      </Card>

      <Card title="Eventos en vivo" description="Del más reciente al más antiguo. Pulsa una partida para ver su razonamiento." padding="none">
        {view.events.length ? (
          <EventFeed events={view.events} total={view.received} onOpenItem={openItem} />
        ) : (
          <EmptyState size="sm" title={view.state === 'connecting' ? 'Esperando los primeros eventos…' : 'Sin eventos'} />
        )}
      </Card>
    </Page>
  )
}

// ---------------------------------------------------------------- route

export default function RunLivePage() {
  const { runId = '' } = useParams()
  const ready = useSessionReady()
  const run = useRunStore((st) => st.runs.find((r) => r.id === runId) ?? null)
  const datasetLoading = useDatasetStore((st) => st.status === 'loading')

  if (run) return <StoredRun run={run} />
  if (!ready || datasetLoading)
    return (
      <Page>
        <QueryState status="loading">{null}</QueryState>
      </Page>
    )
  if (apiConfigured) return <LiveRun key={runId} runId={runId} />
  return (
    <Page>
      <EmptyState
        icon={<SearchX />}
        title="Ejecución no encontrada"
        description={
          <>
            No hay ninguna ejecución <Mono>{runId}</Mono> en los datos activos, y sin VITE_API_URL no hay backend al que preguntar.
          </>
        }
        action={<ButtonLink to="/ejecuciones">Ver ejecuciones</ButtonLink>}
      />
    </Page>
  )
}
