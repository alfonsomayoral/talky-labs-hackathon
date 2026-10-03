// Everything a view needs about one item of the active run: the WorkItem, its delivered rows,
// entries, events, attention and golden comparison. Built from the public stores and engine only.

import { useMemo } from 'react'
import type {
  AgentEvent,
  AttentionItem,
  DatasetApi,
  DatasetCore,
  DerivedRun,
  ItemId,
  ItemScore,
  JournalEntryOut,
  RunBundle,
  WorkItem,
} from '@/domain/types'
import { useDatasetStore } from '@/data/stores'
import { bankAccountItemId, effectiveDeliverables, itemEntries, rowKey, useActiveRun, useDerivedRun } from '@/engine'

export interface ItemContext {
  item: WorkItem
  core: DatasetCore
  api: DatasetApi
  run: RunBundle
  derived: DerivedRun
  /** Delivered rows behind the item: one row, the bank account row, or every close row of the group. */
  rows: Record<string, unknown>[]
  entries: JournalEntryOut[]
  events: AgentEvent[]
  attention: AttentionItem[]
  /** Golden comparison of the item (null without golden). */
  score: ItemScore | null
  /** Bank only: comparison of the whole account (adjustments are scored per account). */
  accountScore: ItemScore | null
}

export type ItemContextState =
  | { status: 'idle' | 'loading' | 'error'; error: string | null; ctx: null }
  | { status: 'missing'; error: null; ctx: null }
  | { status: 'ready'; error: null; ctx: ItemContext }

export function itemRows(run: Pick<RunBundle, 'deliverables' | 'present'>, item: WorkItem): Record<string, unknown>[] {
  const d = effectiveDeliverables(run)
  const rows = d[item.task] as unknown as Record<string, unknown>[]
  if (item.task === 'close') return rows.filter((r) => rowKey('close', r) === item.key)
  const row = rows[item.rowIndex]
  return row ? [row] : []
}

const NO_EVENTS: AgentEvent[] = []

export function useItemContext(itemId: ItemId | null | undefined): ItemContextState {
  const { data, status, error } = useDerivedRun()
  const run = useActiveRun()
  const api = useDatasetStore((s) => s.api)
  return useMemo((): ItemContextState => {
    if (status !== 'ready' || !data || !run || !api) {
      return { status: status === 'ready' ? 'loading' : status, error, ctx: null }
    }
    const item = itemId ? data.itemsById.get(itemId) : undefined
    if (!item) return { status: 'missing', error: null, ctx: null }
    const account = item.task === 'bank_rec' ? item.key.split('/')[0] : null
    return {
      status: 'ready',
      error: null,
      ctx: {
        item,
        core: api.core,
        api,
        run,
        derived: data,
        rows: itemRows(run, item),
        entries: itemEntries(api.core, run, item.id),
        events: data.eventsByItem.get(item.id) ?? NO_EVENTS,
        attention: data.attention.filter((a) => a.item === item.id),
        score: data.score?.perItem[item.id] ?? null,
        accountScore: account ? (data.score?.perItem[bankAccountItemId(account)] ?? null) : null,
      },
    }
  }, [itemId, data, status, error, run, api])
}
