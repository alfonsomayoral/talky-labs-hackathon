// App frame: sidebar + topbar (breadcrumb, page actions slot) + routed content,
// plus the global overlays (item peek, ⌘K palette, shortcuts help) and keyboard shortcuts.
import { lazy, Suspense, useMemo, useState } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router'
import { NAV } from '@/app/nav'
import { Breadcrumb } from '@/components'
import { useGlobalShortcuts } from '@/lib/keyboard'
import { CommandPalette } from './CommandPalette'
import { PageActionsSlotContext } from './PageActions'
import { PeekHost } from './PeekHost'
import { routeCrumbs } from './routeCrumbs'
import { ShortcutsDialog } from './ShortcutsDialog'
import { Sidebar } from './Sidebar'
import { useShellUi } from './uiStore'
import { useEntitySearch } from './useEntitySearch'
import styles from './AppShell.module.css'

// Lazy: the assistant pulls in the item kit, kept out of the main bundle.
const AssistantPanel = lazy(() => import('@/features/assistant/AssistantPanel').then((m) => ({ default: m.AssistantPanel })))

const GO_TO: Record<string, string> = Object.fromEntries(
  NAV.flatMap((s) => s.entries)
    .filter((e) => e.shortcut)
    .map((e) => [e.shortcut as string, e.to]),
)

export default function AppShell() {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const [actionsSlot, setActionsSlot] = useState<HTMLElement | null>(null)
  const togglePalette = useShellUi((s) => s.togglePalette)
  const setHelpOpen = useShellUi((s) => s.setHelpOpen)
  const crumbs = useMemo(() => routeCrumbs(pathname), [pathname])
  useEntitySearch()

  useGlobalShortcuts({
    onPalette: togglePalette,
    onHelp: () => setHelpOpen(true),
    onGo: (letter) => {
      const to = GO_TO[letter]
      if (!to) return false
      navigate(to)
      return true
    },
  })

  return (
    <PageActionsSlotContext.Provider value={actionsSlot}>
      <div className={styles.shell}>
        <Sidebar />
        <div className={styles.main}>
          <header className={styles.topbar}>
            <Breadcrumb items={crumbs} />
            <div ref={setActionsSlot} className={styles.topbarActions} />
          </header>
          <main className={styles.content}>
            <Outlet />
          </main>
        </div>
      </div>
      {/* Before PeekHost so an item opened from the chat sits on top of it. */}
      <Suspense fallback={null}>
        <AssistantPanel />
      </Suspense>
      <PeekHost />
      <CommandPalette />
      <ShortcutsDialog />
    </PageActionsSlotContext.Provider>
  )
}
