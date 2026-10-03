// Item detail panel. Rendered by the shell's PeekHost when the URL has `?item=<task>:<key>`.
import { useEffect, useState } from 'react'
import { ArrowUpRight, Copy, SearchX } from 'lucide-react'
import type { EvidenceRef } from '@/domain/types'
import { outcomeEntry } from '@/domain/catalog/policy'
import {
  Amount,
  Badge,
  Button,
  ButtonLink,
  ConfidenceBand,
  EmptyState,
  IconButton,
  ITEM_STATUS,
  Mono,
  Pill,
  PriorityBadge,
  ProvenanceBadge,
  Skeleton,
  StatusBadge,
  TabPanel,
  Tabs,
  toast,
} from '@/components'
import { formatDate } from '@/lib/format'
import { itemTaskHref, ReasoningView, TASK_META, useItemContext, type ItemContext } from './kit'
import { EntryTab } from './tabs/EntryTab'
import { EvidenceTab, useEvidenceEntries } from './tabs/EvidenceTab'
import { GoldenTab } from './tabs/GoldenTab'
import { SummaryTab } from './tabs/SummaryTab'
import styles from './ItemPanel.module.css'

export interface ItemPanelProps {
  itemId: string
  onClose: () => void
}

type TabId = 'reasoning' | 'summary' | 'entry' | 'evidence' | 'golden'
const TAB_PREFIX = 'item-panel'

export default function ItemPanel({ itemId, onClose }: ItemPanelProps) {
  const state = useItemContext(itemId)
  if (state.status === 'missing') {
    return (
      <div className={styles.empty}>
        <EmptyState
          icon={<SearchX />}
          title="Partida no encontrada"
          description={
            <>
              <Mono>{itemId}</Mono> no está en la ejecución activa. Puede venir de otra ejecución o de un enlace antiguo.
            </>
          }
          action={<Button onClick={onClose}>Cerrar</Button>}
        />
      </div>
    )
  }
  if (state.status === 'error') {
    return (
      <div className={styles.empty}>
        <EmptyState icon={<SearchX />} title="No se pudo cargar la ejecución" description={state.error} />
      </div>
    )
  }
  if (state.status === 'idle') {
    return (
      <div className={styles.empty}>
        <EmptyState icon={<SearchX />} title="Sin ejecución activa" description="Abre una ejecución para ver sus partidas." />
      </div>
    )
  }
  if (!state.ctx) {
    return (
      <div className={styles.loading}>
        <Skeleton width={220} height={20} />
        <Skeleton lines={6} />
      </div>
    )
  }
  return <Panel ctx={state.ctx} />
}

function Panel({ ctx }: { ctx: ItemContext }) {
  const [tab, setTab] = useState<TabId>('reasoning')
  const [focus, setFocus] = useState<string | null>(null)
  const evidence = useEvidenceEntries(ctx)
  const hasGolden = !!ctx.score || !!ctx.accountScore
  const active: TabId = tab === 'golden' && !hasGolden ? 'reasoning' : tab
  const lines = ctx.entries.reduce((s, e) => s + e.lines.length, 0)

  // A new item starts without a focused evidence entry.
  useEffect(() => setFocus(null), [ctx.item.id])

  const onEvidence = (_ref: EvidenceRef, key: string) => {
    setFocus(key)
    setTab('evidence')
  }

  const goldenDiffs = (ctx.score?.diffs.length ?? 0) + (ctx.accountScore?.diffs.length ?? 0)
  const tabs = [
    { id: 'reasoning', label: 'Razonamiento' },
    { id: 'summary', label: 'Resumen' },
    { id: 'entry', label: 'Asiento', count: lines || undefined },
    { id: 'evidence', label: 'Evidencia', count: evidence.length || undefined },
    ...(hasGolden ? [{ id: 'golden', label: goldenDiffs ? 'Golden' : 'Golden ✓', count: goldenDiffs || undefined }] : []),
  ]

  return (
    <div className={styles.panel}>
      <ItemHeader ctx={ctx} />
      <div className={styles.tabs}>
        <Tabs tabs={tabs} value={active} onChange={(id) => setTab(id as TabId)} idPrefix={TAB_PREFIX} aria-label="Detalle de la partida" />
      </div>
      <TabPanel idPrefix={TAB_PREFIX} id={active} className={styles.body}>
        {active === 'reasoning' && <ReasoningView itemId={ctx.item.id} onEvidence={onEvidence} />}
        {active === 'summary' && <SummaryTab ctx={ctx} />}
        {active === 'entry' && <EntryTab ctx={ctx} />}
        {active === 'evidence' && <EvidenceTab entries={evidence} focusKey={focus} />}
        {active === 'golden' && <GoldenTab ctx={ctx} />}
      </TabPanel>
    </div>
  )
}

function ItemHeader({ ctx }: { ctx: ItemContext }) {
  const { item, attention } = ctx
  const meta = TASK_META[item.task]
  const Icon = meta.icon
  const outcome = outcomeEntry(item.task, item.outcome)
  const href = itemTaskHref(item.id)
  const company = item.company ? ctx.core.companies.find((c) => c.code === item.company) : undefined
  const copy = () => {
    navigator.clipboard
      ?.writeText(item.id)
      .then(() => toast.success('Id copiado', { description: item.id }))
      .catch(() => toast.error('No se pudo copiar el id'))
  }
  return (
    <header className={styles.header}>
      <div className={styles.topRow}>
        <span className={styles.task}>
          <Icon aria-hidden />
          {meta.label}
        </span>
        <Mono className={styles.key}>{item.key}</Mono>
        <span className={styles.actions}>
          <IconButton icon={<Copy />} label="Copiar id" size="sm" onClick={copy} />
          {href && (
            <ButtonLink to={href} size="sm" variant="ghost" trailingIcon={<ArrowUpRight aria-hidden />}>
              Ver en su tarea
            </ButtonLink>
          )}
        </span>
      </div>
      <div className={styles.titleRow}>
        <h2 className={styles.title}>{item.title}</h2>
        {item.amount !== null && <Amount cents={item.amount} currency={item.currency ?? 'EUR'} className={styles.amount} />}
      </div>
      <p className={styles.meta}>
        {item.counterparty && <span>{item.counterparty}</span>}
        {item.company && (
          <Pill title={company?.name}>
            {item.company}
            {company ? ` · ${company.short}` : ''}
          </Pill>
        )}
        {item.date && <span>{formatDate(item.date)}</span>}
      </p>
      <div className={styles.badges}>
        <StatusBadge status={item.status} />
        <Badge tone={ITEM_STATUS[item.status].tone} title={outcome?.description}>
          {outcome?.label ?? item.outcome}
        </Badge>
        {outcome?.section && <Mono muted>{outcome.section}</Mono>}
        <ProvenanceBadge provenance={item.provenance} />
        {item.confidence !== null && <ConfidenceBand value={item.confidence} showValue />}
        {attention.map((a) => (
          <PriorityBadge key={a.attention_id || a.title} priority={a.priority} />
        ))}
      </div>
    </header>
  )
}
