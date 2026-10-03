import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { useNavigate } from 'react-router'
import { Command as Cmdk, defaultFilter } from 'cmdk'
import { Blocks, Download, Keyboard, ListVideo, Plus, Search } from 'lucide-react'
import { NAV } from '@/app/nav'
import { Dialog, Kbd } from '@/components'
import { MOD_KEY } from '@/lib/keyboard'
import {
  getCommandProviders,
  getCommandProvidersVersion,
  subscribeCommandProviders,
  type Command,
  type CommandContext,
} from './commands'
import { navIcon } from './icons'
import { useShellUi } from './uiStore'
import { useOpenItem } from './useOpenItem'
import styles from './CommandPalette.module.css'

const DEFAULT_GROUP = 'Resultados'

function builtinCommands(openHelp: () => void): Command[] {
  const nav: Command[] = NAV.flatMap((section) =>
    section.entries.map((entry) => {
      const Icon = navIcon(entry.icon)
      return {
        id: `nav:${entry.to}`,
        label: entry.label,
        group: 'Ir a',
        hint: section.title ?? undefined,
        icon: <Icon />,
        keywords: [section.title ?? '', entry.to],
        shortcut: entry.shortcut ? ['G', entry.shortcut.toUpperCase()] : undefined,
        run: ({ navigate }) => navigate(entry.to),
      }
    }),
  )
  const actions: Command[] = [
    { id: 'act:new-run', label: 'Nuevo cierre', group: 'Acciones', icon: <Plus />, keywords: ['subir', 'dataset', 'cargar'], run: ({ navigate }) => navigate('/ejecuciones/nueva') },
    { id: 'act:runs', label: 'Ver ejecuciones', group: 'Acciones', icon: <ListVideo />, keywords: ['run', 'paquete'], run: ({ navigate }) => navigate('/ejecuciones') },
    { id: 'act:download', label: 'Descargar la entrega…', group: 'Acciones', hint: 'Entregables', icon: <Download />, keywords: ['zip', 'jsonl', 'entregables', 'descargar'], run: ({ navigate }) => navigate('/entregables') },
    { id: 'act:help', label: 'Atajos de teclado', group: 'Acciones', icon: <Keyboard />, shortcut: ['?'], keywords: ['ayuda', 'teclado'], run: () => openHelp() },
  ]
  if (import.meta.env.DEV) {
    actions.push({ id: 'act:gallery', label: 'Galería de componentes', group: 'Acciones', icon: <Blocks />, keywords: ['ui', 'dev'], run: ({ navigate }) => navigate('/dev/ui') })
  }
  return [...nav, ...actions]
}

function filterBuiltins(commands: Command[], query: string): Command[] {
  const q = query.trim()
  if (!q) return commands
  return commands
    .map((c) => ({ c, score: defaultFilter(c.label, q, c.keywords) }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .map((x) => x.c)
}

/** Runs every registered provider for `query`; keeps only the latest query's results. */
function useProviderResults(query: string, enabled: boolean): Command[] {
  const version = useSyncExternalStore(subscribeCommandProviders, getCommandProvidersVersion)
  const [results, setResults] = useState<{ query: string; commands: Command[] }>({ query: '', commands: [] })

  useEffect(() => {
    if (!enabled) return
    let cancelled = false
    const providers = getCommandProviders()
    const collected: Command[][] = providers.map(() => [])
    const publish = () => !cancelled && setResults({ query, commands: collected.flat() })
    providers.forEach((provider, i) => {
      Promise.resolve()
        .then(() => provider(query))
        .then((commands) => {
          collected[i] = commands
          publish()
        })
        .catch((e: unknown) => console.error('Command provider failed', e))
    })
    if (providers.length === 0) publish()
    return () => {
      cancelled = true
    }
  }, [query, enabled, version])

  return results.query === query ? results.commands : []
}

export function CommandPalette() {
  const open = useShellUi((s) => s.paletteOpen)
  const setOpen = useShellUi((s) => s.setPaletteOpen)
  const setHelpOpen = useShellUi((s) => s.setHelpOpen)
  const navigate = useNavigate()
  const openItem = useOpenItem()
  const [query, setQuery] = useState('')

  const builtins = useMemo(() => builtinCommands(() => setHelpOpen(true)), [setHelpOpen])
  const external = useProviderResults(query, open)

  const groups = useMemo(() => {
    const all = [...filterBuiltins(builtins, query), ...external]
    const map = new Map<string, Command[]>()
    for (const c of all) {
      const g = c.group ?? DEFAULT_GROUP
      const list = map.get(g)
      if (list) list.push(c)
      else map.set(g, [c])
    }
    // Searching: entity results first; idle: navigation first.
    const entries = [...map.entries()]
    return query.trim() ? entries.sort(([a], [b]) => Number(a === 'Ir a' || a === 'Acciones') - Number(b === 'Ir a' || b === 'Acciones')) : entries
  }, [builtins, external, query])

  const close = () => {
    setOpen(false)
    setQuery('')
  }

  const run = (command: Command) => {
    close()
    const ctx: CommandContext = { navigate, openItem }
    command.run(ctx)
  }

  return (
    <Dialog open={open} onClose={close} title="Paleta de comandos" bare placement="top" size="md" className={styles.dialog}>
      <Cmdk shouldFilter={false} loop label="Paleta de comandos" className={styles.root}>
        <div className={styles.inputRow}>
          <Search aria-hidden className={styles.searchIcon} />
          <Cmdk.Input value={query} onValueChange={setQuery} placeholder="Busca una página, una acción, un id, un proveedor o una cuenta…" className={styles.input} />
          <Kbd>Esc</Kbd>
        </div>
        <Cmdk.List className={styles.list}>
          <Cmdk.Empty className={styles.empty}>Sin resultados para «{query}»</Cmdk.Empty>
          {groups.map(([group, commands]) => (
            <Cmdk.Group key={group} heading={group} className={styles.group}>
              {commands.map((c) => (
                <Cmdk.Item key={c.id} value={c.id} onSelect={() => run(c)} className={styles.item}>
                  {c.icon && <span className={styles.icon}>{c.icon}</span>}
                  <span className={styles.label}>{c.label}</span>
                  {c.hint && <span className={styles.hint}>{c.hint}</span>}
                  {c.shortcut && (
                    <span className={styles.shortcut}>
                      {c.shortcut.map((k) => (
                        <Kbd key={k}>{k}</Kbd>
                      ))}
                    </span>
                  )}
                </Cmdk.Item>
              ))}
            </Cmdk.Group>
          ))}
        </Cmdk.List>
        <div className={styles.footer}>
          <span>
            <Kbd>↑</Kbd>
            <Kbd>↓</Kbd> navegar
          </span>
          <span>
            <Kbd>↵</Kbd> abrir
          </span>
          <span className={styles.footerEnd}>
            <Kbd>{MOD_KEY}</Kbd>
            <Kbd>K</Kbd> abrir o cerrar
          </span>
        </div>
      </Cmdk>
    </Dialog>
  )
}
