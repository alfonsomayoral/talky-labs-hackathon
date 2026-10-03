// Pieces shared by the /datos pages: section tabs, active dataset, item links and small tables.
import { useMemo, type ReactNode } from 'react'
import { Link, useLocation, useNavigate } from 'react-router'
import { SearchX } from 'lucide-react'
import { Breadcrumb, ButtonLink, EmptyState, KeyValue, Mono, Page, StatusBadge, Tabs, type KeyValueItem } from '@/components'
import type { DatasetApi, DatasetCore, WorkItem } from '@/domain/types'
import { useDatasetStore } from '@/data/stores'
import { useDerivedRun } from '@/engine'
import { useOpenItem } from '@/shell/useOpenItem'
import styles from './DataExplorer.module.css'

const SECTIONS = [
  { id: 'maestros', label: 'Maestros', to: '/datos' },
  { id: 'diario', label: 'Diario', to: '/datos/diario' },
  { id: 'documentos', label: 'Documentos', to: '/datos/documentos' },
  { id: 'extractos', label: 'Extractos', to: '/datos/extractos' },
] as const

/** Top-level navigation inside /datos; detail pages keep their section highlighted. */
export function SectionTabs() {
  const { pathname } = useLocation()
  const navigate = useNavigate()
  const segment = pathname.split('/')[2] ?? ''
  const value = SECTIONS.find((s) => s.id === segment)?.id ?? 'maestros'
  return (
    <Tabs
      aria-label="Secciones de datos"
      tabs={SECTIONS.map((s) => ({ id: s.id, label: s.label }))}
      value={value}
      onChange={(id) => navigate(SECTIONS.find((s) => s.id === id)!.to)}
    />
  )
}

/** The loaded dataset; DataExplorerPage only renders its routes once it exists. */
export function useApi(): DatasetApi {
  return useDatasetStore((s) => s.api)!
}

/** Items of the active run, or null when no run is open (links to items are then hidden). */
export function useRunItems() {
  const { data } = useDerivedRun()
  return data ? { items: data.items, itemsById: data.itemsById } : null
}

export function useCompanyCurrency(core: DatasetCore): (company: string | null | undefined) => string {
  return useMemo(() => {
    const map = new Map(core.companies.map((c) => [c.code, c.currency]))
    return (company) => (company && map.get(company)) || 'EUR'
  }, [core.companies])
}

export function useAccountNames(core: DatasetCore): Map<string, string> {
  return useMemo(() => new Map(core.chartOfAccounts.map((a) => [a.account, a.description])), [core.chartOfAccounts])
}

export function TextLink({ to, children, mono }: { to: string; children: ReactNode; mono?: boolean }) {
  return (
    <Link to={to} className={styles.link} onClick={(e) => e.stopPropagation()}>
      {mono ? <Mono>{children}</Mono> : children}
    </Link>
  )
}

export function DetailHeader({ crumbs, title, subtitle, actions }: { crumbs: { label: string; to?: string }[]; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className={styles.detailHeader}>
      <Breadcrumb items={crumbs} />
      <div className={styles.detailTitleRow}>
        <div>
          <h1 className={styles.detailTitle}>{title}</h1>
          {subtitle != null && <p className={styles.detailSubtitle}>{subtitle}</p>}
        </div>
        {actions}
      </div>
    </header>
  )
}

export function Facts({ items }: { items: KeyValueItem[] }) {
  return (
    <div className={styles.facts}>
      <KeyValue items={items} columns={2} labelWidth={150} />
    </div>
  )
}

/** Items of the run that cite a record; each one opens in the side panel. */
export function ItemLinks({ items, empty }: { items: WorkItem[]; empty: string }) {
  const openItem = useOpenItem()
  if (!items.length) return <p className={styles.muted}>{empty}</p>
  return (
    <ul className={styles.itemList}>
      {items.map((it) => (
        <li key={it.id}>
          <button type="button" className={styles.itemRow} onClick={() => openItem(it.id)}>
            <Mono>{it.key}</Mono>
            <span className={styles.itemTitle}>{it.title}</span>
            <StatusBadge status={it.status} />
          </button>
        </li>
      ))}
    </ul>
  )
}

const ROW = 36
const HEADER = 32

/** Height for a DataTable that sits among other blocks: grows with its rows up to `max`. */
export const tableHeight = (rows: number, max = 360) => Math.min(max, HEADER + Math.max(rows, 3) * ROW + 2)

export function NotFound({ what = 'Esta página de datos no existe' }: { what?: string }) {
  return (
    <Page>
      <EmptyState
        icon={<SearchX />}
        title={what}
        description="Puede que el id no esté en el dataset cargado."
        action={<ButtonLink to="/datos">Volver a Datos</ButtonLink>}
      />
    </Page>
  )
}
