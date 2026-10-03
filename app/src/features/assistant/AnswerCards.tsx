// Renders the cards of an answer. Items open the shell's side panel; reasoning and process maps
// reuse the item kit (TraceTimeline, ProcessMap) so they look the same as everywhere else.

import { Fragment, useMemo, useState, type ReactNode } from 'react'
import { ArrowUpRight } from 'lucide-react'
import { Amount, Button, KeyValue, Metric, Mono, PriorityBadge, Skeleton, StatusBadge, type KeyValueItem } from '@/components'
import type { ItemId, TaskKey, WorkItem } from '@/domain/types'
import { useDerivedRun } from '@/engine'
import { ProcessMap, TraceTimeline, itemEurCents, useProcessFlow, type FlowFilter } from '@/features/item/kit'
import { useDatasetStore } from '@/data/stores'
import { formatNumber, formatPercent } from '@/lib/format'
import { useOpenItem } from '@/shell/useOpenItem'
import type { AssistantCard, CardItem, Citation, MetricValue, TableCell } from './engine'
import styles from './Assistant.module.css'

const EMPTY_ITEMS: ReadonlyMap<ItemId, WorkItem> = new Map()

function useItemsById(): ReadonlyMap<ItemId, WorkItem> {
  return useDerivedRun().data?.itemsById ?? EMPTY_ITEMS
}

export function AnswerCards({ cards }: { cards: AssistantCard[] }) {
  return (
    <>
      {cards.map((card, i) => (
        <AnswerCard key={`${card.type}-${i}`} card={card} />
      ))}
    </>
  )
}

function AnswerCard({ card }: { card: AssistantCard }) {
  switch (card.type) {
    case 'metric':
      return (
        <CardFrame title={card.title}>
          <div className={styles.metrics}>
            {card.metrics.map((m) => (
              <Metric key={m.label} label={m.label} value={<MetricValueView value={m.value} />} delta={m.delta} comparison={m.comparison} hint={m.hint} />
            ))}
          </div>
        </CardFrame>
      )
    case 'table':
      return (
        <CardFrame title={card.title} flush>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  {card.columns.map((c, i) => (
                    <th key={i} data-align={c.align}>
                      {c.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {card.rows.map((row, r) => (
                  <tr key={r}>
                    {row.map((cell, c) => (
                      <td key={c} data-align={card.columns[c]?.align}>
                        <CellView cell={cell} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardFrame>
      )
    case 'items':
      return (
        <CardFrame title={card.title} flush note={card.total && card.total > card.items.length ? `${formatNumber(card.items.length)} de ${formatNumber(card.total)}` : undefined}>
          <ItemList items={card.items} />
        </CardFrame>
      )
    case 'reasoning':
      return <ReasoningCard card={card} />
    case 'process':
      return <ProcessCard task={card.task} />
  }
}

function CardFrame({ title, note, flush, children }: { title?: string; note?: string; flush?: boolean; children: ReactNode }) {
  return (
    <section className={styles.card}>
      {(title || note) && (
        <header className={styles.cardHeader}>
          {title && <h3 className={styles.cardTitle}>{title}</h3>}
          {note && <span className={styles.cardNote}>{note}</span>}
        </header>
      )}
      <div className={flush ? undefined : styles.cardBody}>{children}</div>
    </section>
  )
}

function MetricValueView({ value }: { value: MetricValue }) {
  switch (value.kind) {
    case 'number':
      return <>{formatNumber(value.value)}</>
    case 'percent':
      return <>{formatPercent(value.value)}</>
    case 'money':
      return <Amount cents={value.cents} currency={value.currency} compact />
    case 'text':
      return <>{value.text}</>
  }
}

function CellView({ cell }: { cell: TableCell }) {
  const openItem = useOpenItem()
  switch (cell.kind) {
    case 'text':
      return <>{cell.text}</>
    case 'mono':
      return <Mono>{cell.text}</Mono>
    case 'number':
      return <span className="tabular">{formatNumber(cell.value)}</span>
    case 'percent':
      return <span className="tabular">{formatPercent(cell.value)}</span>
    case 'money':
      return (
        <>
          {cell.amounts.map((a, i) => (
            <Fragment key={a.currency}>
              {i > 0 && ' + '}
              <Amount cents={a.cents} currency={a.currency} />
            </Fragment>
          ))}
        </>
      )
    case 'item':
      return (
        <button type="button" className={styles.inlineItem} onClick={() => openItem(cell.item)}>
          <Mono>{cell.label}</Mono>
        </button>
      )
    default:
      return null
  }
}

/** Rows that open the item in the side panel; fields the card lacks come from the active run. */
export function ItemList({ items }: { items: CardItem[] }) {
  const openItem = useOpenItem()
  const itemsById = useItemsById()
  return (
    <ul className={styles.items}>
      {items.map((ci, i) => {
        const it = itemsById.get(ci.item)
        const status = ci.status ?? it?.status
        const amount = ci.amount !== undefined ? ci.amount : (it?.amount ?? null)
        return (
          <li key={`${ci.item}-${i}`}>
            <button type="button" className={styles.itemRow} onClick={() => openItem(ci.item)}>
              {ci.priority ? <PriorityBadge priority={ci.priority} /> : status ? <StatusBadge status={status} /> : <span />}
              <span className={styles.itemText}>
                <span className={styles.itemTitle}>{ci.title ?? it?.title ?? ci.item}</span>
                <span className={styles.itemSub}>
                  <Mono muted>{it?.key ?? ci.item}</Mono>
                  {it?.counterparty && <span> · {it.counterparty}</span>}
                </span>
              </span>
              <Amount cents={amount} currency={ci.currency ?? it?.currency ?? 'EUR'} compact />
            </button>
          </li>
        )
      })}
    </ul>
  )
}

function ReasoningCard({ card }: { card: Extract<AssistantCard, { type: 'reasoning' }> }) {
  const openItem = useOpenItem()
  const facts: KeyValueItem[] = card.facts.map((f) => ({
    label: f.label,
    value: (
      <span className={styles.fact}>
        {f.mono && <Mono>{f.mono}</Mono>}
        {f.text && <span>{f.text}</span>}
        {f.cents !== undefined && <Amount cents={f.cents} currency={f.currency ?? 'EUR'} />}
      </span>
    ),
  }))
  return (
    <section className={styles.card}>
      <header className={styles.cardHeader}>
        <h3 className={styles.cardTitle}>
          Razonamiento de <Mono>{card.item.slice(card.item.indexOf(':') + 1)}</Mono>
        </h3>
        <Button size="sm" variant="ghost" trailingIcon={<ArrowUpRight aria-hidden />} onClick={() => openItem(card.item)}>
          Abrir partida
        </Button>
      </header>
      <div className={styles.cardBody}>
        {card.headline && <p className={styles.headlineText}>{card.headline}</p>}
        {facts.length > 0 && <KeyValue items={facts} labelWidth={112} />}
        {card.steps.length > 0 && <TraceTimeline steps={card.steps} onEvidence={() => openItem(card.item)} />}
      </div>
    </section>
  )
}

const FLOW_LIST = 8

function ProcessCard({ task }: { task: TaskKey }) {
  const flow = useProcessFlow(task)
  const core = useDatasetStore((s) => s.api?.core ?? null)
  const itemsById = useItemsById()
  const [selected, setSelected] = useState<FlowFilter | null>(null)
  const items = useMemo((): CardItem[] => {
    if (!selected || !core) return []
    return [...selected.items]
      .map((id) => itemsById.get(id))
      .filter((it): it is WorkItem => !!it)
      .sort((a, b) => Math.abs(itemEurCents(b, b.amount ?? 0, core)) - Math.abs(itemEurCents(a, a.amount ?? 0, core)))
      .slice(0, FLOW_LIST)
      .map((it) => ({ item: it.id }))
  }, [selected, core, itemsById])

  if (!flow) {
    return (
      <section className={styles.card}>
        <div className={styles.cardBody}>
          <Skeleton height={160} radius="var(--radius-md)" />
        </div>
      </section>
    )
  }
  return (
    <section className={styles.card}>
      <header className={styles.cardHeader}>
        <h3 className={styles.cardTitle}>{flow.title}</h3>
        <span className={styles.cardNote}>Pulsa un camino para ver sus partidas</span>
      </header>
      <div className={styles.cardBody}>
        <ProcessMap flow={flow} selectedId={selected?.id ?? null} onSelect={setSelected} aria-label={`Mapa de decisión: ${flow.title}`} />
      </div>
      {selected && (
        <div className={styles.flowItems}>
          <p className={styles.cardNote}>
            {selected.label}: {formatNumber(selected.items.size)} {selected.items.size === 1 ? 'partida' : 'partidas'}
            {selected.items.size > FLOW_LIST ? `, las ${FLOW_LIST} de mayor importe` : ''}
          </p>
          <ItemList items={items} />
        </div>
      )}
    </section>
  )
}

export function Citations({ citations }: { citations: Citation[] }) {
  const openItem = useOpenItem()
  const items = [...new Set(citations.flatMap((c) => ('item' in c ? [c.item] : [])))]
  const refs = [...new Set(citations.flatMap((c) => ('policy_ref' in c ? [c.policy_ref] : [])))]
  if (!items.length && !refs.length) return null
  return (
    <div className={styles.citations}>
      <span className={styles.citationsLabel}>Fuentes</span>
      {items.map((id) => (
        <button key={id} type="button" className={styles.citation} onClick={() => openItem(id)} title="Abrir la partida en el panel">
          <Mono>{id.slice(id.indexOf(':') + 1)}</Mono>
        </button>
      ))}
      {refs.map((r) => (
        <span key={r} className={styles.policyRef}>
          <Mono>{r}</Mono>
        </span>
      ))}
    </div>
  )
}
