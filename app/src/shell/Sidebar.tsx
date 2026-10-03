import { useMemo } from 'react'
import { NavLink } from 'react-router'
import clsx from 'clsx'
import { Blocks, Command, Keyboard } from 'lucide-react'
import { NAV, type NavEntry } from '@/app/nav'
import { Kbd, Tooltip } from '@/components'
import { useActiveRun, useAttention } from '@/engine/useDerivedRun'
import { useOverridesStore } from '@/features/attention/overridesStore'
import { formatNumber } from '@/lib/format'
import { MOD_KEY } from '@/lib/keyboard'
import { pendingAttention } from './attentionBadge'
import { ContextSwitcher } from './ContextSwitcher'
import { navIcon } from './icons'
import { useShellUi } from './uiStore'
import styles from './Sidebar.module.css'

function NavItem({ entry, badge, urgent }: { entry: NavEntry; badge?: number; urgent?: boolean }) {
  const Icon = navIcon(entry.icon)
  const link = (
    <NavLink to={entry.to} end={entry.to === '/'} className={({ isActive }) => clsx(styles.entry, isActive && styles.active)}>
      <Icon aria-hidden className={styles.entryIcon} />
      <span className={styles.entryLabel}>{entry.label}</span>
      {badge != null && badge > 0 && (
        <span className={clsx(styles.badge, urgent && styles.badgeUrgent, 'tabular')} aria-label={`${badge} pendientes`}>
          {formatNumber(badge)}
        </span>
      )}
    </NavLink>
  )
  if (!entry.shortcut) return link
  return (
    <Tooltip content={`Ir a ${entry.label}`} shortcut={['G', entry.shortcut.toUpperCase()]} side="right" delay={700}>
      {link}
    </Tooltip>
  )
}

export function Sidebar() {
  const attentionItems = useAttention()
  const runId = useActiveRun()?.id
  const overrides = useOverridesStore((s) => (runId ? s.byRun[runId] : undefined))
  const { count: attention, urgent } = useMemo(() => pendingAttention(attentionItems, overrides ?? []), [attentionItems, overrides])
  const togglePalette = useShellUi((s) => s.togglePalette)
  const setHelpOpen = useShellUi((s) => s.setHelpOpen)

  return (
    <aside className={styles.sidebar}>
      <div className={styles.top}>
        <ContextSwitcher />
      </div>

      <nav className={styles.nav} aria-label="Principal">
        {NAV.map((section, i) => (
          <div key={section.title ?? i} className={styles.section}>
            {section.title && <div className={styles.sectionTitle}>{section.title}</div>}
            <ul className={styles.entries}>
              {section.entries.map((entry) => (
                <li key={entry.to}>
                  <NavItem entry={entry} badge={entry.badge === 'attention' ? attention : undefined} urgent={urgent} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className={styles.footer}>
        {import.meta.env.DEV && (
          <NavLink to="/dev/ui" className={({ isActive }) => clsx(styles.entry, styles.footerEntry, isActive && styles.active)}>
            <Blocks aria-hidden className={styles.entryIcon} />
            <span className={styles.entryLabel}>Galería UI</span>
          </NavLink>
        )}
        <button type="button" className={clsx(styles.entry, styles.footerEntry)} onClick={togglePalette}>
          <Command aria-hidden className={styles.entryIcon} />
          <span className={styles.entryLabel}>Comandos</span>
          <span className={styles.keys}>
            <Kbd>{MOD_KEY}</Kbd>
            <Kbd>K</Kbd>
          </span>
        </button>
        <button type="button" className={clsx(styles.entry, styles.footerEntry)} onClick={() => setHelpOpen(true)}>
          <Keyboard aria-hidden className={styles.entryIcon} />
          <span className={styles.entryLabel}>Atajos</span>
          <span className={styles.keys}>
            <Kbd>?</Kbd>
          </span>
        </button>
      </div>
    </aside>
  )
}
