import { useMemo } from 'react'
import clsx from 'clsx'
import { ArrowUpRight, History, Workflow } from 'lucide-react'
import type { ApRow, AttentionItem, EvidenceRef, ItemId, WorkItem } from '@/domain/types'
import {
  AP_ACTION_CATALOG,
  AP_PAYEE_CATALOG,
  AP_REASON_CATALOG,
  outcomeEntry,
  reasonEntry,
} from '@/domain/catalog/policy'
import { Amount, Badge, ConfidenceBand, EmptyState, ITEM_STATUS, Mono, PriorityBadge, ProvenanceBadge, Skeleton, StatusBadge } from '@/components'
import { useOpenItem } from '@/shell/useOpenItem'
import { formatDuration, formatNumber, formatPercent } from '@/lib/format'
import { ApMasterCompare } from './MasterCompare'
import { BankMatchFacts } from './BankMatchFacts'
import { apCascade, reasoningSteps, reasoningSummary, type ReasoningFact } from './reasoning'
import { TraceTimeline } from './TraceTimeline'
import { useItemContext, type ItemContext } from './useItemContext'
import styles from './ReasoningView.module.css'

export interface ReasoningViewProps {
  itemId: ItemId
  /** Click on an evidence chip of a step (the item panel opens it in Evidencia). */
  onEvidence?: (ref: EvidenceRef, key: string) => void
  className?: string
}

/** Why the agent decided what it did, as an ordered narrative ending in the decision and its § of the policy. */
export function ReasoningView({ itemId, onEvidence, className }: ReasoningViewProps) {
  const state = useItemContext(itemId)
  if (state.status === 'error') return <EmptyState size="sm" icon={<History />} title="No se pudo cargar la partida" description={state.error} />
  if (state.status === 'missing') return <EmptyState size="sm" icon={<History />} title="Partida no encontrada" description={`${itemId} no está en la ejecución activa.`} />
  if (!state.ctx) return <Skeleton lines={6} />
  return <Reasoning ctx={state.ctx} onEvidence={onEvidence} className={className} />
}

function Reasoning({ ctx, onEvidence, className }: { ctx: ItemContext; onEvidence?: ReasoningViewProps['onEvidence']; className?: string }) {
  const { item, rows, core, entries, events, derived } = ctx
  const apRow = item.task === 'ap' ? ((rows[0] ?? null) as Partial<ApRow> | null) : null
  const cascade = useMemo(() => (apRow ? apCascade(apRow, events) : null), [apRow, events])
  const steps = useMemo(() => reasoningSteps(events, cascade), [events, cascade])
  const summary = useMemo(() => reasoningSummary({ item, rows, core, entries }), [item, rows, core, entries])
  const synthesized = derived.eventsSynthesized
  const totalMs = events.reduce((s, e) => s + (e.duration_ms ?? 0), 0)
  const banks = item.evidence.filter((e) => e.kind === 'bank').length
  const books = item.evidence.filter((e) => e.kind === 'journal').length

  return (
    <div className={clsx(styles.view, className)}>
      <div className={styles.origin} data-synthesized={synthesized || undefined}>
        {synthesized ? <History aria-hidden /> : <Workflow aria-hidden />}
        {synthesized ? (
          <span>
            <strong>Traza reconstruida desde la entrega.</strong> El paquete no trae <Mono>trace/events.jsonl</Mono>: los pasos se deducen de la decisión, los motivos y el asiento
            entregados.
          </span>
        ) : (
          <span>
            <strong>Traza del agente</strong> · {formatNumber(events.length)} {events.length === 1 ? 'evento' : 'eventos'}
            {totalMs > 0 ? ` · ${formatDuration(totalMs)}` : ''}
          </span>
        )}
      </div>

      <section className={styles.why}>
        <p className={styles.headline}>{summary.headline}</p>
        {item.task === 'bank_rec' && banks > 0 && books > 0 && <BankMatchFacts item={item} />}
        <Facts facts={summary.facts} />
      </section>

      {apRow && apRow.decision !== 'NOT_INVOICE' && <ApMasterCompare row={apRow} />}

      <section className={styles.section}>
        <h4 className={styles.sectionTitle}>Pasos</h4>
        {steps.length ? (
          <TraceTimeline steps={steps} onEvidence={onEvidence} />
        ) : (
          <p className={styles.muted}>La ejecución no trae eventos para esta partida.</p>
        )}
      </section>

      <DecisionCard ctx={ctx} />
    </div>
  )
}

function Facts({ facts }: { facts: ReasoningFact[] }) {
  if (!facts.length) return null
  return (
    <dl className={styles.facts}>
      {facts.map((f, i) => (
        <div key={`${f.label}-${i}`} className={styles.fact} data-tone={f.tone}>
          <dt>{f.label}</dt>
          <dd>
            {f.mono && <Mono>{f.mono}</Mono>}
            {f.text && <span>{f.text}</span>}
            {f.cents !== undefined && <Amount cents={f.cents} currency={f.currency ?? 'EUR'} />}
          </dd>
        </div>
      ))}
    </dl>
  )
}

function DecisionCard({ ctx }: { ctx: ItemContext }) {
  const { item, rows, attention } = ctx
  const openItem = useOpenItem()
  const outcome = outcomeEntry(item.task, item.outcome)
  const row = (rows[0] ?? {}) as Record<string, unknown>
  const tone = ITEM_STATUS[item.status].tone
  const reasons = item.reasons
    .filter((r) => !(item.task === 'ap' && r === 'DUPLICATE'))
    .map((r) => ({ code: r, entry: reasonEntry(item.task, r) ?? (item.task === 'ap' ? AP_REASON_CATALOG[r as keyof typeof AP_REASON_CATALOG] : null) }))
  const action = item.task === 'ap' && typeof row.action === 'string' && row.action !== 'NONE' ? AP_ACTION_CATALOG[row.action as keyof typeof AP_ACTION_CATALOG] : null
  const payeeType = item.task === 'ap' && row.payee && typeof row.payee === 'object' ? String((row.payee as Record<string, unknown>).type) : null
  const payee = payeeType ? AP_PAYEE_CATALOG[payeeType as keyof typeof AP_PAYEE_CATALOG] : null
  const payeeInfo = row.payee as { name?: string; iban?: string } | null
  const dupOf = item.task === 'ap' && typeof row.duplicate_of === 'string' ? row.duplicate_of : null
  const dupExists = dupOf ? ctx.derived.itemsById.has(`ap:${dupOf}`) : false

  return (
    <section className={styles.decision} data-tone={tone}>
      <header className={styles.decisionHead}>
        <span className={styles.decisionLabel}>Decisión</span>
        <Badge tone={tone}>{outcome?.label ?? item.outcome}</Badge>
        {(outcome?.section ?? item.policyRefs[0]) && <Mono className={styles.policy}>{outcome?.section ?? item.policyRefs[0]}</Mono>}
      </header>
      {outcome?.description && <p className={styles.explanation}>{outcome.description}</p>}

      {reasons.length > 0 && (
        <ul className={styles.reasons}>
          {reasons.map(({ code, entry }) => (
            <li key={code}>
              <strong>{entry?.label ?? code}</strong>
              {entry?.section && <Mono muted> {entry.section}</Mono>}
              {entry?.description && <span className={styles.reasonText}> — {entry.description}</span>}
            </li>
          ))}
        </ul>
      )}

      {action && (
        <p className={styles.block}>
          <strong>Acción:</strong> {action.label}. <span className={styles.reasonText}>{action.description}</span>
        </p>
      )}
      {dupOf && (
        <p className={styles.block}>
          <strong>Original:</strong> <Mono>{dupOf}</Mono>
          {dupExists && (
            <button type="button" className={styles.link} onClick={() => openItem(`ap:${dupOf}`)}>
              Abrir <ArrowUpRight aria-hidden />
            </button>
          )}
        </p>
      )}
      {payee && (
        <p className={styles.block}>
          <strong>{payee.label}:</strong> {payee.description}
          {payeeInfo?.name && (
            <span className={styles.reasonText}>
              {' '}
              {payeeInfo.name}
              {payeeInfo.iban ? (
                <>
                  {' · '}
                  <Mono>{payeeInfo.iban}</Mono>
                </>
              ) : null}
            </span>
          )}
        </p>
      )}
      {item.task === 'ap' && row.payment_block ? (
        <p className={styles.block}>
          <strong>Bloqueo de pago:</strong> certificado del art. 43 caducado a la fecha de la factura (§2.2.4).
        </p>
      ) : null}

      <footer className={styles.decisionFoot}>
        <StatusBadge status={item.status} />
        <ProvenanceBadge provenance={item.provenance} />
        {item.confidence !== null && <ConfidenceBand value={item.confidence} showValue />}
      </footer>

      {attention.map((a) => (
        <AttentionNote key={a.attention_id || a.title} attention={a} item={item} />
      ))}
    </section>
  )
}

function AttentionNote({ attention: a }: { attention: AttentionItem; item: WorkItem }) {
  return (
    <div className={styles.attention}>
      <PriorityBadge priority={a.priority} />
      <div className={styles.attentionText}>
        <strong>{a.title}</strong>
        {a.suggested_action && <span>{a.suggested_action}</span>}
        {a.alternatives && a.alternatives.length > 0 && (
          <span className={styles.reasonText}>Alternativas: {a.alternatives.map((x) => `${x.decision} (${formatPercent(x.p, { decimals: 0 })})`).join(', ')}</span>
        )}
      </div>
    </div>
  )
}
