// Sidebar navigation (Spanish labels). Icons are lucide-react names resolved by the shell.
export interface NavEntry {
  to: string
  label: string
  icon: string
  /** Keyboard shortcut after `g` (Linear style), e.g. `g` then `r`. */
  shortcut?: string
  /** Badge source: number of open attention items, etc. */
  badge?: 'attention'
}

export interface NavSection {
  title: string | null
  entries: NavEntry[]
}

export const NAV: NavSection[] = [
  {
    title: null,
    entries: [
      { to: '/', label: 'Resumen', icon: 'LayoutDashboard', shortcut: 'r' },
      { to: '/atencion', label: 'Atención', icon: 'Inbox', shortcut: 'a', badge: 'attention' },
      { to: '/actividad', label: 'Actividad', icon: 'Activity', shortcut: 'y' },
      { to: '/asistente', label: 'Asistente', icon: 'Sparkles', shortcut: 'i' },
    ],
  },
  {
    title: 'Tareas',
    entries: [
      { to: '/tareas/ap', label: 'Bandeja AP', icon: 'FileText', shortcut: '1' },
      { to: '/tareas/facturacion', label: 'Facturación', icon: 'Receipt', shortcut: '2' },
      { to: '/tareas/cobros', label: 'Cobros', icon: 'HandCoins', shortcut: '3' },
      { to: '/tareas/bancos', label: 'Bancos', icon: 'Landmark', shortcut: '4' },
      { to: '/tareas/intragrupo', label: 'Intragrupo', icon: 'Network', shortcut: '5' },
      { to: '/tareas/cierre', label: 'Cierre', icon: 'CalendarCheck', shortcut: '6' },
    ],
  },
  {
    title: 'Contabilidad',
    entries: [
      { to: '/balance', label: 'Balance', icon: 'Scale', shortcut: 'b' },
      { to: '/datos', label: 'Datos', icon: 'Database', shortcut: 'd' },
    ],
  },
  {
    title: 'Entrega',
    entries: [
      { to: '/entregables', label: 'Entregables', icon: 'PackageCheck', shortcut: 'e' },
      { to: '/ejecuciones', label: 'Ejecuciones', icon: 'Play', shortcut: 'x' },
      { to: '/comparar', label: 'Comparar', icon: 'GitCompare', shortcut: 'c' },
      { to: '/coste', label: 'Coste', icon: 'Gauge', shortcut: 'o' },
    ],
  },
]
