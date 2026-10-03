// Ejecuciones: runs of the active dataset with their origin, files, score and manifest; activate,
// open or delete them, and pull bundles served by the dev middleware or the backend.
import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { CloudDownload, Ellipsis, Eye, Play, Plus, Trash2, Upload } from 'lucide-react'
import {
  Amount,
  Badge,
  Button,
  ButtonLink,
  DataTable,
  Dialog,
  EmptyState,
  IconButton,
  Menu,
  Mono,
  Page,
  PageHeader,
  toast,
  type Column,
} from '@/components'
import { useDatasetStore, useRunStore } from '@/data/stores'
import type { RunBundle } from '@/domain/types'
import { useDerivedRun } from '@/engine'
import { formatDateTime, formatDuration, formatMonth, formatNumber } from '@/lib/format'
import { SourceBadge } from './SourceBadge'
import { filesPresent, rowsDelivered, runPath } from './taskMeta'
import s from './RunsPage.module.css'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
/** Stops row clicks/Enter from reaching the DataTable row (React events bubble through portals). */
const Isolate = ({ children }: { children: ReactNode }) => (
  <span className={s.isolate} onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
    {children}
  </span>
)

function RemoteRunsList({ onLoaded }: { onLoaded: () => void }) {
  const listRemoteRuns = useRunStore((st) => st.listRemoteRuns)
  const loadRemoteRun = useRunStore((st) => st.loadRemoteRun)
  const [list, setList] = useState<{ id: string; label: string; source: string }[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    listRemoteRuns().then(
      (l) => alive && setList(l),
      (e: unknown) => {
        if (!alive) return
        setList([])
        setError(message(e))
      },
    )
    return () => {
      alive = false
    }
  }, [listRemoteRuns])

  const load = (id: string) => {
    setLoading(id)
    loadRemoteRun(id)
      .then(
        (run) => {
          toast.success('Ejecución cargada', { description: run.label })
          onLoaded()
        },
        (e: unknown) => toast.error('No se pudo cargar la ejecución', { description: message(e) }),
      )
      .finally(() => setLoading(null))
  }

  if (list === null) return <p className={s.muted}>Buscando…</p>
  if (list.length === 0) return <p className={s.muted}>{error ?? 'No hay ejecuciones remotas para este dataset.'}</p>
  return (
    <ul className={s.remoteList}>
      {list.map((r) => (
        <li key={r.id}>
          <span className={s.remoteLabel}>{r.label}</span>
          <Mono muted>{r.id}</Mono>
          <span className={s.grow} />
          <Button size="sm" loading={loading === r.id} disabled={loading !== null && loading !== r.id} onClick={() => load(r.id)}>
            Cargar
          </Button>
        </li>
      ))}
    </ul>
  )
}

export default function RunsPage() {
  const navigate = useNavigate()
  const meta = useDatasetStore((st) => st.api?.meta ?? null)
  const datasetStatus = useDatasetStore((st) => st.status)
  const runs = useRunStore((st) => st.runs)
  const activeId = useRunStore((st) => st.activeId)
  const setActive = useRunStore((st) => st.setActive)
  const removeRun = useRunStore((st) => st.remove)
  const { data } = useDerivedRun()
  const [confirm, setConfirm] = useState<RunBundle | null>(null)
  const [remoteOpen, setRemoteOpen] = useState(false)

  const rows = useMemo(() => (meta ? runs.filter((r) => r.datasetId === meta.id) : []), [runs, meta])

  const columns = useMemo<Column<RunBundle>[]>(() => {
    const derived = (r: RunBundle) => (r.id === activeId && data?.runId === r.id ? data : null)
    return [
      {
        id: 'label',
        header: 'Ejecución',
        width: 'minmax(180px, 2fr)',
        sortValue: (r) => r.label,
        cell: (r) => (
          <span className={s.labelCell}>
            <span className={s.label} title={r.id}>
              {r.label}
            </span>
            {r.id === activeId && <Badge tone="brand">Activa</Badge>}
          </span>
        ),
      },
      { id: 'source', header: 'Origen', width: 128, sortValue: (r) => r.source, cell: (r) => <SourceBadge source={r.source} /> },
      { id: 'created', header: 'Creada', width: 136, sortValue: (r) => r.createdAt, cell: (r) => <span className={s.muted}>{formatDateTime(r.createdAt)}</span> },
      {
        id: 'files',
        header: 'Ficheros',
        width: 84,
        align: 'right',
        sortValue: filesPresent,
        cell: (r) => <span className={filesPresent(r) < 6 ? s.warn : undefined}>{filesPresent(r)}/6</span>,
      },
      { id: 'rows', header: 'Filas', width: 64, align: 'right', sortValue: rowsDelivered, cell: (r) => formatNumber(rowsDelivered(r)) },
      {
        id: 'items',
        header: 'Partidas',
        width: 76,
        align: 'right',
        cell: (r) => {
          const d = derived(r)
          return d ? formatNumber(d.stats.items) : <span className={s.muted} title="Actívala para derivar sus partidas">—</span>
        },
      },
      {
        id: 'score',
        header: 'Nota',
        width: 68,
        align: 'right',
        cell: (r) => {
          const score = derived(r)?.score
          return score ? <strong className="tabular">{formatNumber(score.total, { decimals: 2 })}</strong> : <span className={s.muted}>—</span>
        },
      },
      {
        id: 'model',
        header: 'Modelo',
        width: 'minmax(96px, 1fr)',
        cell: (r) => {
          const models = r.manifest?.models?.map((m) => m.name) ?? []
          return models.length ? <Mono title={models.join(', ')}>{models.join(', ')}</Mono> : <span className={s.muted}>—</span>
        },
      },
      {
        id: 'cost',
        header: 'Coste',
        width: 80,
        align: 'right',
        sortValue: (r) => r.manifest?.cost_usd_total ?? null,
        cell: (r) => (r.manifest?.cost_usd_total != null ? <Amount cents={Math.round(r.manifest.cost_usd_total * 100)} currency="USD" /> : <span className={s.muted}>—</span>),
      },
      {
        id: 'runtime',
        header: 'Duración',
        width: 84,
        align: 'right',
        sortValue: (r) => r.manifest?.runtime_s ?? null,
        cell: (r) => (r.manifest?.runtime_s != null ? formatDuration(r.manifest.runtime_s * 1000) : <span className={s.muted}>—</span>),
      },
      {
        id: 'actions',
        header: <span className="sr-only">Acciones</span>,
        width: 40,
        align: 'right',
        cell: (r) => (
          <Isolate>
            <Menu
              align="end"
              aria-label={`Acciones de ${r.label}`}
              trigger={<IconButton size="sm" icon={<Ellipsis />} label="Acciones" tooltip={false} />}
              items={[
                { id: 'open', label: 'Ver ejecución', icon: <Eye />, onSelect: () => navigate(runPath(r.id)) },
                { id: 'activate', label: 'Activar', icon: <Play />, disabled: r.id === activeId, onSelect: () => setActive(r.id) },
                { type: 'separator', id: 'sep' },
                { id: 'delete', label: 'Eliminar', icon: <Trash2 />, danger: true, onSelect: () => setConfirm(r) },
              ]}
            />
          </Isolate>
        ),
      },
    ]
  }, [activeId, data, navigate, setActive])

  const header = (
    <PageHeader
      title="Ejecuciones"
      subtitle={meta ? `${meta.name} · ${formatMonth(meta.month)} · ${rows.length === 1 ? '1 ejecución' : `${formatNumber(rows.length)} ejecuciones`}` : 'Resultados del agente por dataset.'}
      actions={
        <>
          {meta && (
            <Button leadingIcon={<CloudDownload />} onClick={() => setRemoteOpen(true)}>
              Buscar ejecuciones remotas
            </Button>
          )}
          <ButtonLink to="/ejecuciones/nueva" variant="primary" leadingIcon={<Plus />}>
            Nuevo cierre
          </ButtonLink>
        </>
      }
    />
  )

  return (
    <Page fill>
      {header}
      {!meta ? (
        <EmptyState
          icon={<Upload />}
          title={datasetStatus === 'loading' ? 'Cargando datos…' : 'Sin datos cargados'}
          description="Las ejecuciones van ligadas a los datos de un mes. Carga una fase para empezar."
          action={
            <ButtonLink to="/ejecuciones/nueva" variant="primary">
              Nuevo cierre
            </ButtonLink>
          }
        />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={<Play />}
          title="Sin ejecuciones"
          description="Lanza el cierre con el backend, importa las 6 JSONL o abre la referencia."
          action={
            <ButtonLink to="/ejecuciones/nueva" variant="primary">
              Nuevo cierre
            </ButtonLink>
          }
        />
      ) : (
        <DataTable aria-label="Ejecuciones" rows={rows} columns={columns} getRowId={(r) => r.id} onOpen={(r) => navigate(runPath(r.id))} globalKeys />
      )}

      <Dialog
        open={remoteOpen}
        onClose={() => setRemoteOpen(false)}
        title="Ejecuciones remotas"
        description="Paquetes servidos por el middleware de desarrollo (KALMORA_RUNS) o por el backend."
      >
        {remoteOpen && <RemoteRunsList onLoaded={() => setRemoteOpen(false)} />}
      </Dialog>

      <Dialog
        open={confirm !== null}
        onClose={() => setConfirm(null)}
        size="sm"
        title="Eliminar ejecución"
        description={confirm ? `Se quita «${confirm.label}» de este navegador. Los ficheros originales no se tocan.` : undefined}
        footer={
          <>
            <Button onClick={() => setConfirm(null)}>Cancelar</Button>
            <Button
              variant="danger"
              onClick={() => {
                const run = confirm
                setConfirm(null)
                if (run) void removeRun(run.id).then(() => toast('Ejecución eliminada', { description: run.label }))
              }}
            >
              Eliminar
            </Button>
          </>
        }
      />
    </Page>
  )
}
