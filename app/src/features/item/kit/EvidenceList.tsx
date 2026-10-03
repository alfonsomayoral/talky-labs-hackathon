import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import clsx from 'clsx'
import { BookOpen, ChevronRight, Database, FileText, History, Landmark, Link2, type LucideIcon } from 'lucide-react'
import type { EvidenceRef, JournalEntryOut } from '@/domain/types'
import { useDatasetStore } from '@/data/stores'
import { EmptyState, Skeleton } from '@/components'
import { DocumentViewer } from './DocumentViewer'
import { findErpRecord, parseBookLine } from './evidence'
import { JournalEntryView } from './JournalEntryView'
import { JsonView } from './JsonView'
import { RawBankRecord } from './RawBankRecord'
import { useAsync } from './useAsync'
import styles from './EvidenceList.module.css'

export type EvidenceKind = EvidenceRef['kind'] | 'related'

export interface EvidenceEntry {
  /** Unique key; for refs use `evidenceKey(ref)` so trace chips can focus it. */
  key: string
  kind: EvidenceKind
  /** Section heading the entry is listed under (e.g. «Documentos», «Maestros»). */
  group: string
  title: string
  subtitle?: string
  ref?: EvidenceRef
  /** Custom body; defaults to the viewer of `ref`. */
  render?: () => ReactNode
}

export interface EvidenceListProps {
  entries: EvidenceEntry[]
  /** Entry to open and scroll to (e.g. after a click on a trace chip). */
  focusKey?: string | null
  /** Entries open at first. */
  defaultOpen?: string[]
  className?: string
}

const ICONS: Record<EvidenceKind, LucideIcon> = {
  doc: FileText,
  erp: Database,
  bank: Landmark,
  journal: BookOpen,
  precedent: History,
  related: Link2,
}

/** Grouped, expandable list of the evidence behind an item; each entry opens its viewer inline. */
export function EvidenceList({ entries, focusKey, defaultOpen, className }: EvidenceListProps) {
  const [open, setOpen] = useState<ReadonlySet<string>>(() => new Set(defaultOpen ?? []))
  const rowRefs = useRef(new Map<string, HTMLElement>())
  const groups = useMemo(() => {
    const m = new Map<string, EvidenceEntry[]>()
    for (const e of entries) m.set(e.group, [...(m.get(e.group) ?? []), e])
    return [...m]
  }, [entries])

  useEffect(() => {
    if (!focusKey) return
    setOpen((prev) => new Set([...prev, focusKey]))
    const el = rowRefs.current.get(focusKey)
    el?.scrollIntoView?.({ block: 'start', behavior: 'smooth' })
  }, [focusKey])

  if (!entries.length) return <EmptyState size="sm" icon={<FileText />} title="Sin evidencia" description="La entrega no enlaza documentos, maestros ni líneas para esta partida." />

  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })

  return (
    <div className={clsx(styles.list, className)}>
      {groups.map(([group, list]) => (
        <section key={group} className={styles.group}>
          <h4 className={styles.groupTitle}>
            {group}
            <span className={styles.count}>{list.length}</span>
          </h4>
          <ul className={styles.entries}>
            {list.map((e) => {
              const Icon = ICONS[e.kind]
              const isOpen = open.has(e.key)
              return (
                <li
                  key={e.key}
                  ref={(el) => {
                    if (el) rowRefs.current.set(e.key, el)
                    else rowRefs.current.delete(e.key)
                  }}
                  className={clsx(styles.entry, focusKey === e.key && styles.focused)}
                >
                  <button type="button" className={styles.row} aria-expanded={isOpen} onClick={() => toggle(e.key)}>
                    <ChevronRight aria-hidden className={clsx(styles.chevron, isOpen && styles.open)} />
                    <Icon aria-hidden className={styles.icon} />
                    <span className={styles.title}>{e.title}</span>
                    {e.subtitle && <span className={styles.subtitle}>{e.subtitle}</span>}
                  </button>
                  {isOpen && <div className={styles.body}>{e.render ? e.render() : e.ref ? <EvidenceBody evidence={e.ref} /> : null}</div>}
                </li>
              )
            })}
          </ul>
        </section>
      ))}
    </div>
  )
}

/** Default viewer of an evidence reference. */
export function EvidenceBody({ evidence }: { evidence: EvidenceRef }) {
  switch (evidence.kind) {
    case 'doc':
      return <DocumentViewer path={evidence.path} />
    case 'erp':
      return <ErpRecord file={evidence.file} recordKey={evidence.key} />
    case 'bank':
      return <RawBankRecord bankLine={evidence.bank_line} />
    case 'journal':
      return <BookLine bookLine={evidence.book_line} />
    case 'precedent':
      return <p className={styles.precedent}>{evidence.text}</p>
  }
}

export function ErpRecord({ file, recordKey }: { file: string; recordKey: string }) {
  const core = useDatasetStore((s) => s.api?.core ?? null)
  const record = core ? findErpRecord(core, file, recordKey) : null
  if (record === null || record === undefined) {
    return <p className={styles.muted}>No está en los datos cargados ({file}).</p>
  }
  return <JsonView value={record} depth={1} />
}

/** A recorded journal entry, with the referenced line (`<id>#<line>`) highlighted. */
export function BookLine({ bookLine }: { bookLine: string }) {
  const api = useDatasetStore((s) => s.api)
  const { entryId, line } = parseBookLine(bookLine)
  const state = useAsync(async () => (api ? ((await api.getJournalEntries([entryId]))[0] ?? null) : null), [api, entryId])
  if (state.status === 'loading') return <Skeleton lines={3} />
  if (state.status === 'error') return <p role="alert" className={styles.muted}>No se pudo leer el diario: {state.error}</p>
  if (!state.data) return <p className={styles.muted}>El asiento {entryId} no está en el diario cargado.</p>
  return <JournalEntryView entry={state.data as unknown as JournalEntryOut} highlight={line !== null ? [line] : undefined} />
}
