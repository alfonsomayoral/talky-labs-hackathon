// Registers the ⌘K entity search (4.D): items and master data from memory, journal entries from the worker.
import { useEffect, useMemo, useRef } from 'react'
import { BookOpen, BookText, Landmark, Truck, Users, type LucideIcon } from 'lucide-react'
import { NAV } from '@/app/nav'
import { useDatasetStore } from '@/data/stores'
import type { DatasetApi } from '@/domain/types'
import { useDerivedRun } from '@/engine/useDerivedRun'
import { registerCommandProvider, type Command } from './commands'
import { buildEntityIndex, journalHit, searchEntities, TASK_ROUTE, type SearchHit } from './entitySearch'
import { navIcon } from './icons'

const GROUP_ICON: Record<string, LucideIcon> = {
  Proveedores: Truck,
  Clientes: Users,
  Cuentas: BookOpen,
  'Líneas bancarias': Landmark,
  Asientos: BookText,
}

const NAV_BY_ROUTE = new Map(NAV.flatMap((s) => s.entries).map((e) => [e.to, e]))

/** Journal ids are long (`1100-2026-1400000003`); shorter queries would scan the journal for little. */
const MIN_JOURNAL_QUERY = 6
const JOURNAL_LIMIT = 5

function toCommand(hit: SearchHit): Command {
  const { target } = hit
  if (target.kind === 'item') {
    const Icon = navIcon(NAV_BY_ROUTE.get(TASK_ROUTE[target.task])?.icon ?? '')
    return { id: hit.id, label: hit.label, hint: hit.hint, group: hit.group, icon: <Icon />, run: ({ openItem }) => openItem(target.itemId) }
  }
  const Icon = GROUP_ICON[hit.group]
  return { id: hit.id, label: hit.label, hint: hit.hint, group: hit.group, icon: Icon && <Icon />, run: ({ navigate }) => navigate(target.to) }
}

/** The top item also gets «Ver en <tarea>»: its task page with the panel open. */
function goToTask(hit: SearchHit): Command | null {
  if (hit.target.kind !== 'item') return null
  const route = TASK_ROUTE[hit.target.task]
  const entry = NAV_BY_ROUTE.get(route)
  const Icon = navIcon(entry?.icon ?? '')
  const itemId = hit.target.itemId
  return {
    id: `task:${hit.id}`,
    label: `Ver en ${entry?.label ?? 'su tarea'}`,
    hint: hit.label.split(' · ')[0],
    group: 'Acciones',
    icon: <Icon />,
    run: ({ navigate }) => navigate(`${route}?item=${encodeURIComponent(itemId)}`),
  }
}

export function useEntitySearch() {
  const api = useDatasetStore((s) => s.api)
  const items = useDerivedRun().data?.items
  const index = useMemo(() => (api ? buildEntityIndex(api.core, items ?? []) : null), [api, items])

  const latest = useRef<{ index: typeof index; api: DatasetApi | null }>({ index, api })
  useEffect(() => {
    latest.current = { index, api }
  })

  useEffect(() => {
    const offEntities = registerCommandProvider((query) => {
      const { index } = latest.current
      if (!index) return []
      const hits = searchEntities(index, query)
      const firstItem = hits.find((h) => h.target.kind === 'item')
      const extra = firstItem ? goToTask(firstItem) : null
      return [...hits.map(toCommand), ...(extra ? [extra] : [])]
    })
    const offJournal = registerCommandProvider(async (query) => {
      const { api } = latest.current
      const q = query.trim().toLowerCase()
      if (!api || q.length < MIN_JOURNAL_QUERY) return []
      const { entries } = await api.queryJournal({ text: q, limit: JOURNAL_LIMIT })
      return entries.map((e) => toCommand(journalHit(e)))
    })
    return () => {
      offEntities()
      offJournal()
    }
  }, [])
}
