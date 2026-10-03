// Administración: every dataset and run stored in this browser, with the dataset each run belongs to,
// and removal of either after confirmation. Nothing on the backend or on disk is touched.
import { useEffect, useMemo, useState } from 'react'
import { Database, Trash2 } from 'lucide-react'
import { Badge, Card, DataTable, EmptyState, IconButton, Page, PageHeader, toast, type Column } from '@/components'
import { useDatasetStore, useRunStore } from '@/data/stores'
import type { DatasetMeta, RunBundle } from '@/domain/types'
import { formatDateTime, formatMonth, formatNumber } from '@/lib/format'
import { ConfirmRemove, type RemoveTarget } from './ConfirmRemove'
import { SourceBadge } from './SourceBadge'
import { filesPresent } from './taskMeta'
import s from './AdminPage.module.css'

const SOURCE_KIND: Record<DatasetMeta['sourceKind'], string> = { folder: 'Carpeta', zip: 'Zip', http: 'Servido' }
const ROW = 36
const HEADER = 32
/** Room for up to 10 rows, plus a horizontal scrollbar on narrow screens. */
const tableHeight = (rows: number) => HEADER + Math.max(1, Math.min(rows, 10)) * ROW + 16

interface RunRow {
  run: RunBundle
  dataset: DatasetMeta
}

export default function AdminPage() {
  const datasets = useDatasetStore((st) => st.datasets)
  const activeDatasetId = useDatasetStore((st) => st.activeId)
  const removeDataset = useDatasetStore((st) => st.remove)
  const openRuns = useRunStore((st) => st.runs)
  const activeRunId = useRunStore((st) => st.activeId)
  const runsOf = useRunStore((st) => st.runsOf)
  const removeRun = useRunStore((st) => st.remove)
  const [stored, setStored] = useState<Record<string, RunBundle[]> | null>(null)
  const [version, setVersion] = useState(0)
  const [confirm, setConfirm] = useState<RemoveTarget | null>(null)

  useEffect(() => {
    let alive = true
    Promise.all(datasets.map(async (d) => [d.id, await runsOf(d.id)] as const)).then((entries) => alive && setStored(Object.fromEntries(entries)))
    return () => {
      alive = false
    }
  }, [datasets, openRuns, runsOf, version])

  const runRows = useMemo<RunRow[]>(() => datasets.flatMap((dataset) => (stored?.[dataset.id] ?? []).map((run) => ({ run, dataset }))), [datasets, stored])

  const datasetColumns = useMemo<Column<DatasetMeta>[]>(
    () => [
      {
        id: 'name',
        header: 'Dataset',
        width: 'minmax(180px, 2fr)',
        sortValue: (d) => d.name,
        cell: (d) => (
          <span className={s.labelCell}>
            <span className={s.label} title={d.id}>
              {d.name}
            </span>
            {d.id === activeDatasetId && <Badge tone="brand">Activo</Badge>}
          </span>
        ),
      },
      { id: 'month', header: 'Mes', width: 120, sortValue: (d) => d.month, cell: (d) => formatMonth(d.month) },
      { id: 'source', header: 'Origen', width: 96, sortValue: (d) => d.sourceKind, cell: (d) => SOURCE_KIND[d.sourceKind] },
      { id: 'loaded', header: 'Cargado', width: 136, sortValue: (d) => d.loadedAt, cell: (d) => <span className={s.muted}>{formatDateTime(d.loadedAt)}</span> },
      {
        id: 'runs',
        header: 'Ejecuciones',
        width: 120,
        align: 'right',
        sortValue: (d) => stored?.[d.id]?.length ?? null,
        cell: (d) => (stored ? formatNumber(stored[d.id]?.length ?? 0) : <span className={s.muted}>—</span>),
      },
      {
        id: 'actions',
        header: <span className="sr-only">Acciones</span>,
        width: 48,
        align: 'right',
        cell: (d) => {
          const count = stored?.[d.id]?.length ?? 0
          return (
            <IconButton
              size="sm"
              icon={<Trash2 />}
              label={`Eliminar ${d.name}`}
              onClick={() =>
                setConfirm({
                  title: 'Eliminar dataset',
                  description: `Se quita «${d.name}»${count === 0 ? '' : count === 1 ? ' con su ejecución' : ` con sus ${formatNumber(count)} ejecuciones`} de este navegador.${d.id === activeDatasetId ? ' Es el dataset activo: la app se queda sin datos cargados.' : ''} Los ficheros originales no se tocan.`,
                  run: () => removeDataset(d.id).then(() => void toast('Dataset eliminado', { description: d.name })),
                })
              }
            />
          )
        },
      },
    ],
    [activeDatasetId, removeDataset, stored],
  )

  const runColumns = useMemo<Column<RunRow>[]>(
    () => [
      {
        id: 'label',
        header: 'Ejecución',
        width: 'minmax(140px, 2fr)',
        sortValue: (r) => r.run.label,
        cell: ({ run, dataset }) => (
          <span className={s.labelCell}>
            <span className={s.label} title={run.id}>
              {run.label}
            </span>
            {dataset.id === activeDatasetId && run.id === activeRunId && <Badge tone="brand">Activa</Badge>}
          </span>
        ),
      },
      {
        id: 'dataset',
        header: 'Datos',
        width: 'minmax(160px, 2fr)',
        sortValue: (r) => `${r.dataset.name} ${r.dataset.month}`,
        cell: ({ dataset }) => (
          <span className={s.labelCell} title={dataset.id}>
            <span className={s.datasetName}>{dataset.name}</span>
            <Badge variant="outline">{formatMonth(dataset.month)}</Badge>
          </span>
        ),
      },
      { id: 'source', header: 'Origen', width: 128, sortValue: (r) => r.run.source, cell: (r) => <SourceBadge source={r.run.source} /> },
      { id: 'created', header: 'Creada', width: 136, sortValue: (r) => r.run.createdAt, cell: (r) => <span className={s.muted}>{formatDateTime(r.run.createdAt)}</span> },
      { id: 'files', header: 'Ficheros', width: 84, align: 'right', sortValue: (r) => filesPresent(r.run), cell: (r) => `${filesPresent(r.run)}/6` },
      {
        id: 'actions',
        header: <span className="sr-only">Acciones</span>,
        width: 48,
        align: 'right',
        cell: ({ run, dataset }) => (
          <IconButton
            size="sm"
            icon={<Trash2 />}
            label={`Eliminar ${run.label}`}
            onClick={() =>
              setConfirm({
                title: 'Eliminar ejecución',
                description: `Se quita «${run.label}» de ${dataset.name} en este navegador. Los ficheros originales no se tocan.`,
                run: () =>
                  removeRun(run.id, dataset.id).then(() => {
                    setVersion((v) => v + 1)
                    toast('Ejecución eliminada', { description: run.label })
                  }),
              })
            }
          />
        ),
      },
    ],
    [activeDatasetId, activeRunId, removeRun],
  )

  return (
    <Page>
      <PageHeader title="Administración" subtitle="Datasets y ejecuciones guardados en este navegador." />
      {datasets.length === 0 ? (
        <EmptyState icon={<Database />} title="Nada guardado" description="Los datasets y las ejecuciones aparecen aquí al cargarlos desde Nuevo cierre." />
      ) : (
        <>
          <Card title="Datasets" description="Al eliminar un dataset se eliminan también sus ejecuciones." padding="none">
            <DataTable aria-label="Datasets" rows={datasets} columns={datasetColumns} getRowId={(d) => d.id} height={tableHeight(datasets.length)} />
          </Card>
          <Card title="Ejecuciones" description="Todas las ejecuciones, con el dataset del que salen. Las remotas solo se quitan de este navegador." padding="none">
            {runRows.length ? (
              <DataTable
                aria-label="Ejecuciones de todos los datasets"
                rows={runRows}
                columns={runColumns}
                getRowId={(r) => `${r.dataset.id}/${r.run.id}`}
                height={tableHeight(runRows.length)}
              />
            ) : (
              <EmptyState size="sm" title={stored ? 'Sin ejecuciones' : 'Cargando…'} />
            )}
          </Card>
        </>
      )}
      <ConfirmRemove target={confirm} onClose={() => setConfirm(null)} />
    </Page>
  )
}
