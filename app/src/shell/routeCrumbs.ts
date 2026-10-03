// Topbar breadcrumb derived from the URL and the NAV labels.
import { NAV, type NavEntry, type NavSection } from '@/app/nav'
import type { BreadcrumbItem } from '@/components/Breadcrumb/Breadcrumb'

const SEGMENT_LABELS: Record<string, string> = {
  nueva: 'Nuevo cierre',
}

const DEV_PAGES: Record<string, string> = {
  '/dev/ui': 'Galería de componentes',
  '/dev/data': 'Datos (depuración)',
}

function matches(entry: NavEntry, pathname: string): boolean {
  if (entry.to === '/') return pathname === '/'
  return pathname === entry.to || pathname.startsWith(`${entry.to}/`)
}

function segmentLabel(segment: string): string {
  const decoded = decodeURIComponent(segment)
  return SEGMENT_LABELS[decoded] ?? (/^[a-zñáéíóú-]+$/.test(decoded) ? decoded.charAt(0).toUpperCase() + decoded.slice(1) : decoded)
}

export function routeCrumbs(pathname: string, nav: NavSection[] = NAV): BreadcrumbItem[] {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname
  if (DEV_PAGES[path]) return [{ label: 'Desarrollo' }, { label: DEV_PAGES[path] }]

  let best: { section: NavSection; entry: NavEntry } | null = null
  for (const section of nav) {
    for (const entry of section.entries) {
      if (matches(entry, path) && (!best || entry.to.length > best.entry.to.length)) best = { section, entry }
    }
  }
  if (!best) return [{ label: 'Página no encontrada' }]

  const { section, entry } = best
  const items: BreadcrumbItem[] = []
  if (section.title) items.push({ label: section.title })
  items.push({ label: entry.label, to: entry.to })
  const rest = path.slice(entry.to.length).split('/').filter(Boolean)
  rest.forEach((segment, i) => {
    items.push({ label: segmentLabel(segment), to: `${entry.to}/${rest.slice(0, i + 1).join('/')}` })
  })
  return items
}
