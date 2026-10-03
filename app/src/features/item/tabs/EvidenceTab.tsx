import { useMemo } from 'react'
import { useOpenItem } from '@/shell/useOpenItem'
import { EvidenceList, type EvidenceEntry, type ItemContext } from '../kit'
import { buildEvidenceEntries } from './evidenceEntries'

export function useEvidenceEntries(ctx: ItemContext | null): EvidenceEntry[] {
  const openItem = useOpenItem()
  return useMemo(() => (ctx ? buildEvidenceEntries(ctx, openItem) : []), [ctx, openItem])
}

/** Documents, masters, bank lines and book lines behind the item; `focusKey` opens one (from a trace chip). */
export function EvidenceTab({ entries, focusKey }: { entries: EvidenceEntry[]; focusKey: string | null }) {
  return <EvidenceList entries={entries} focusKey={focusKey} defaultOpen={entries.length === 1 ? [entries[0].key] : undefined} />
}
