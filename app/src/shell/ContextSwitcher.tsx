// Sidebar header: active dataset + month + run, with a menu to switch among them.
import { useNavigate } from 'react-router'
import { ChevronsUpDown, ListVideo, Plus } from 'lucide-react'
import { Menu, toast, type MenuItem } from '@/components'
import { useDatasetStore, useRunStore } from '@/data/stores'
import { formatDateTime, formatMonth } from '@/lib/format'
import styles from './Sidebar.module.css'

export function ContextSwitcher() {
  const navigate = useNavigate()
  const datasets = useDatasetStore((s) => s.datasets)
  const activeDatasetId = useDatasetStore((s) => s.activeId)
  const activate = useDatasetStore((s) => s.activate)
  const runs = useRunStore((s) => s.runs)
  const activeRunId = useRunStore((s) => s.activeId)
  const setActiveRun = useRunStore((s) => s.setActive)

  const dataset = datasets.find((d) => d.id === activeDatasetId) ?? null
  const datasetRuns = runs.filter((r) => !activeDatasetId || r.datasetId === activeDatasetId)
  const run = runs.find((r) => r.id === activeRunId) ?? null

  const items: MenuItem[] = [
    { type: 'label', id: 'h-ds', label: 'Dataset' },
    ...(datasets.length
      ? datasets.map<MenuItem>((d) => ({
          id: `ds:${d.id}`,
          label: d.name,
          hint: formatMonth(d.month),
          checked: d.id === activeDatasetId,
          onSelect: () => {
            activate(d.id).catch((e: unknown) =>
              toast.error('No se pudo abrir el dataset', { description: e instanceof Error ? e.message : String(e) }),
            )
          },
        }))
      : [{ id: 'ds:none', label: 'Ningún dataset cargado', disabled: true, checked: false, onSelect: () => {} }]),
    { type: 'separator', id: 's1' },
    { type: 'label', id: 'h-run', label: 'Ejecución' },
    ...(datasetRuns.length
      ? datasetRuns.map<MenuItem>((r) => ({
          id: `run:${r.id}`,
          label: r.label,
          hint: formatDateTime(r.createdAt),
          checked: r.id === activeRunId,
          onSelect: () => setActiveRun(r.id),
        }))
      : [{ id: 'run:none', label: 'Sin ejecuciones', disabled: true, checked: false, onSelect: () => {} }]),
    { type: 'separator', id: 's2' },
    { id: 'new', label: 'Nuevo cierre', icon: <Plus />, onSelect: () => navigate('/ejecuciones/nueva') },
    { id: 'all', label: 'Ver ejecuciones', icon: <ListVideo />, onSelect: () => navigate('/ejecuciones') },
  ]

  const subtitle = dataset ? [formatMonth(dataset.month), run?.label ?? 'Sin ejecución'].join(' · ') : 'Nuevo cierre para empezar'

  return (
    <Menu
      aria-label="Cambiar dataset o ejecución"
      className={styles.switcherMenu}
      items={items}
      trigger={
        <button type="button" className={styles.switcher}>
          <span className={styles.mark} aria-hidden>
            K
          </span>
          <span className={styles.switcherText}>
            <span className={styles.switcherName}>{dataset ? dataset.name : 'Sin datos cargados'}</span>
            <span className={styles.switcherSub}>{subtitle}</span>
          </span>
          <ChevronsUpDown aria-hidden className={styles.switcherIcon} />
        </button>
      }
    />
  )
}
