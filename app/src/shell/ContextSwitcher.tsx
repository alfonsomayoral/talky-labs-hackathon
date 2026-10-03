// Sidebar header: Talky mark + the data's group, month and run, with a menu to switch dataset or run.
import { useNavigate } from 'react-router'
import { ChevronsUpDown, ListVideo, Plus } from 'lucide-react'
import { Menu, TalkyMark, toast, type MenuItem } from '@/components'
import { useDatasetStore, useRunStore } from '@/data/stores'
import { formatDateTime, formatMonth } from '@/lib/format'
import { groupName, monthLabel } from './groupName'
import styles from './Sidebar.module.css'

export function ContextSwitcher() {
  const navigate = useNavigate()
  const datasets = useDatasetStore((s) => s.datasets)
  const activeDatasetId = useDatasetStore((s) => s.activeId)
  const activate = useDatasetStore((s) => s.activate)
  const companies = useDatasetStore((s) => s.api?.core.companies)
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

  const name = groupName(companies) ?? dataset?.name ?? 'Sin datos cargados'
  const subtitle = dataset ? [monthLabel(dataset.month), run?.label ?? 'Sin ejecución'].join(' · ') : 'Nuevo cierre para empezar'

  return (
    <Menu
      aria-label="Cambiar dataset o ejecución"
      className={styles.switcherMenu}
      items={items}
      trigger={
        <button type="button" className={styles.switcher}>
          <TalkyMark className={styles.mark} />
          <span className={styles.switcherText}>
            <span className={styles.switcherName}>{name}</span>
            <span className={styles.switcherSub}>{subtitle}</span>
          </span>
          <ChevronsUpDown aria-hidden className={styles.switcherIcon} />
        </button>
      }
    />
  )
}
