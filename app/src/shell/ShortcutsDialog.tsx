import { NAV } from '@/app/nav'
import { Dialog, Kbd } from '@/components'
import { MOD_KEY } from '@/lib/keyboard'
import { useShellUi } from './uiStore'
import styles from './AppShell.module.css'

interface Shortcut {
  label: string
  keys: string[]
}

const GENERAL: Shortcut[] = [
  { label: 'Paleta de comandos', keys: [MOD_KEY, 'K'] },
  { label: 'Atajos de teclado', keys: ['?'] },
  { label: 'Cerrar panel o diálogo', keys: ['Esc'] },
]

const LISTS: Shortcut[] = [
  { label: 'Fila siguiente', keys: ['J'] },
  { label: 'Fila anterior', keys: ['K'] },
  { label: 'Moverse con flechas', keys: ['↑', '↓'] },
  { label: 'Abrir partida', keys: ['↵'] },
]

function Group({ title, items }: { title: string; items: Shortcut[] }) {
  return (
    <section className={styles.shortcutGroup}>
      <h3 className={styles.shortcutTitle}>{title}</h3>
      <dl>
        {items.map((s) => (
          <div key={s.label} className={styles.shortcutRow}>
            <dt>{s.label}</dt>
            <dd>
              {s.keys.map((k) => (
                <Kbd key={k}>{k}</Kbd>
              ))}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

export function ShortcutsDialog() {
  const open = useShellUi((s) => s.helpOpen)
  const setOpen = useShellUi((s) => s.setHelpOpen)
  const goTo: Shortcut[] = NAV.flatMap((s) => s.entries)
    .filter((e) => e.shortcut)
    .map((e) => ({ label: e.label, keys: ['G', (e.shortcut ?? '').toUpperCase()] }))

  return (
    <Dialog open={open} onClose={() => setOpen(false)} title="Atajos de teclado" size="lg">
      <div className={styles.shortcuts}>
        <div className={styles.shortcutColumn}>
          <Group title="General" items={GENERAL} />
          <Group title="Listas" items={LISTS} />
        </div>
        <Group title="Ir a" items={goTo} />
      </div>
    </Dialog>
  )
}
