// One attention entry: a dense row that expands into the agent's recommendation and the actions.
import clsx from 'clsx'
import { Bot, Check, ChevronDown, ChevronRight, Clock, CopyCheck, ListTree, Scale, StickyNote, Workflow } from 'lucide-react'
import { Amount, Badge, Button, ConfidenceBand, KeyValue, Menu, Mono, Pill, Tooltip, type MenuItem } from '@/components'
import { formatPercent } from '@/lib/format'
import { TASK_LABEL } from '@/domain/catalog/labels'
import { decisionLabel, decisionOptions, kindLabel, policyDescription, reasonLabel, rowKeyLabel, type AttentionRow } from './attentionModel'
import styles from './AttentionPage.module.css'

export interface RowActions {
  select(r: AttentionRow): void
  accept(r: AttentionRow): void
  choose(r: AttentionRow, decision: string): void
  snooze(r: AttentionRow): void
  note(r: AttentionRow): void
  open(r: AttentionRow): void
  similar(r: AttentionRow): void
}

interface Props {
  row: AttentionRow
  selected: boolean
  expanded: boolean
  /** Other pending rows «Aplicar a similares» would accept (only computed for the expanded row). */
  similarCount: number
  actions: RowActions
}

export function PolicyChip({ row }: { row: AttentionRow }) {
  const ref = row.a.policy_ref
  if (!ref) return null
  const description = policyDescription(row)
  const chip = (
    <span className={styles.policy} tabIndex={description ? 0 : undefined}>
      <Mono>{ref}</Mono>
    </span>
  )
  return description ? <Tooltip content={description}>{chip}</Tooltip> : chip
}

export function AttentionCard({ row, selected, expanded, similarCount, actions }: Props) {
  const { a, item, task } = row
  const open = selected && expanded
  return (
    <div data-key={row.key} className={clsx(styles.card, selected && styles.selected, open && styles.open)} aria-current={selected || undefined}>
      <div className={styles.row} onClick={() => actions.select(row)}>
        <span className={styles.chevron} aria-hidden>
          {open ? <ChevronDown /> : <ChevronRight />}
        </span>
        <Mono className={styles.key} title={a.item}>
          {rowKeyLabel(row)}
        </Mono>
        <span className={styles.titleCell}>
          <span className={styles.title}>{a.title}</span>
          {item?.counterparty && <span className={styles.counterparty}>{item.counterparty}</span>}
          {row.override?.note && <StickyNote className={styles.noteIcon} aria-label="Con nota" />}
        </span>
        <span className={styles.badges}>
          <Badge variant="outline" className={styles.kind}>
            {kindLabel(a.kind)}
          </Badge>
          <PolicyChip row={row} />
          {a.affects_tb && (
            <Badge variant="outline" icon={<Scale aria-hidden />}>
              Afecta al balance
            </Badge>
          )}
          <ConfidenceBand value={a.confidence} />
        </span>
        <span className={styles.where}>
          {task ? TASK_LABEL[task] : '—'}
          {item?.company && <Mono muted>{item.company}</Mono>}
        </span>
        <Amount className={styles.amount} cents={a.impact} currency={item?.currency ?? 'EUR'} />
      </div>
      {open && <Detail row={row} similarCount={similarCount} actions={actions} />}
    </div>
  )
}

function Detail({ row, similarCount, actions }: Omit<Props, 'selected' | 'expanded'>) {
  const { a, item, task } = row
  const decision = a.recommendation?.decision ?? null
  const reasons = a.recommendation?.reasons ?? []
  const { alternatives, others } = decisionOptions(row)
  const bars = [...(decision && a.confidence != null ? [{ decision, label: decisionLabel(task, decision), p: a.confidence, recommended: true }] : []), ...alternatives.map((x) => ({ ...x, p: x.p ?? 0, recommended: false }))]

  const menuItems: MenuItem[] = [
    ...(alternatives.length > 0 ? [{ type: 'label' as const, id: 'alt', label: 'Alternativas del agente' }] : []),
    ...alternatives.map((x) => ({ id: `a-${x.decision}`, label: x.label, hint: formatPercent(x.p, { decimals: 0 }), onSelect: () => actions.choose(row, x.decision) })),
    ...(alternatives.length > 0 && others.length > 0 ? [{ type: 'separator' as const, id: 'sep' }] : []),
    ...(others.length > 0 ? [{ type: 'label' as const, id: 'other', label: 'Otras decisiones' }] : []),
    ...others.map((x) => ({ id: `o-${x.decision}`, label: x.label, hint: <Mono muted>{x.decision}</Mono>, onSelect: () => actions.choose(row, x.decision) })),
  ]

  return (
    <div className={styles.detail}>
      <div className={styles.detailGrid}>
        <div className={styles.detailMain}>
          <div className={styles.block}>
            <span className={styles.blockLabel}>Recomendación del agente</span>
            <div className={styles.decision}>
              <strong>{decision ? decisionLabel(task, decision) : 'Sin decisión'}</strong>
              {decision && <Mono muted>{decision}</Mono>}
            </div>
            {reasons.length > 0 && (
              <div className={styles.reasons}>
                {reasons.map((r) => (
                  <Pill key={r}>{reasonLabel(task, r)}</Pill>
                ))}
              </div>
            )}
          </div>
          {bars.length > 0 && (
            <div className={styles.block}>
              <span className={styles.blockLabel}>Alternativas</span>
              <div className={styles.bars}>
                {bars.map((b) => (
                  <div key={b.decision} className={styles.barRow}>
                    <span className={styles.barLabel}>
                      {b.label}
                      {b.recommended && <span className={styles.barTag}>recomendada</span>}
                    </span>
                    <span className={styles.barTrack} aria-hidden>
                      <span className={clsx(styles.barFill, b.recommended && styles.barFillStrong)} style={{ width: `${Math.round(b.p * 100)}%` }} />
                    </span>
                    <span className={clsx(styles.barValue, 'tabular')}>{formatPercent(b.p, { decimals: 0 })}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {a.suggested_action && (
            <div className={styles.block}>
              <span className={styles.blockLabel}>Acción sugerida</span>
              <p className={styles.text}>{a.suggested_action}</p>
            </div>
          )}
          {row.override?.note && (
            <div className={styles.block}>
              <span className={styles.blockLabel}>Nota</span>
              <p className={styles.text}>{row.override.note}</p>
            </div>
          )}
        </div>
        <KeyValue
          className={styles.meta}
          labelWidth={92}
          items={[
            {
              label: 'Origen',
              value: a.derived ? (
                <Badge variant="outline" icon={<Workflow aria-hidden />} title="La app derivó esta entrada con sus reglas porque la ejecución no trae attention.jsonl">
                  Heurística de la app
                </Badge>
              ) : (
                <Badge variant="outline" icon={<Bot aria-hidden />}>
                  Agente
                </Badge>
              ),
            },
            { label: 'Confianza', value: a.confidence != null ? <ConfidenceBand value={a.confidence} showValue /> : <span className={styles.muted}>Sin dato</span> },
            {
              label: 'Política',
              value: a.policy_ref ? (
                <span className={styles.policyText}>
                  <Mono>{a.policy_ref}</Mono> {policyDescription(row)}
                </span>
              ) : null,
            },
            { label: 'Tipo', value: kindLabel(a.kind) },
            { label: 'Balance', value: a.affects_tb ? 'Afecta al balance' : 'No lo mueve' },
            { label: 'Tarea', value: [task ? TASK_LABEL[task] : null, item?.company].filter(Boolean).join(' · ') || null },
            { label: 'Partida', value: a.item, mono: true },
            { label: 'Contraparte', value: item?.counterparty ?? null },
          ]}
        />
      </div>
      <div className={styles.actions}>
        <Tooltip content="Aceptar la recomendación" shortcut={['A']}>
          <Button variant="primary" size="sm" leadingIcon={<Check aria-hidden />} onClick={() => actions.accept(row)}>
            Aceptar
          </Button>
        </Tooltip>
        <Menu
          aria-label="Elegir alternativa"
          className={styles.menu}
          items={menuItems}
          trigger={
            <Button size="sm" trailingIcon={<ChevronDown aria-hidden />} disabled={menuItems.length === 0}>
              Elegir alternativa
            </Button>
          }
        />
        <Tooltip content="Sacar de la cola por ahora" shortcut={['P']}>
          <Button size="sm" variant="ghost" leadingIcon={<Clock aria-hidden />} onClick={() => actions.snooze(row)}>
            Posponer
          </Button>
        </Tooltip>
        <Tooltip content="Añadir una nota" shortcut={['N']}>
          <Button size="sm" variant="ghost" leadingIcon={<StickyNote aria-hidden />} onClick={() => actions.note(row)}>
            Nota
          </Button>
        </Tooltip>
        <Tooltip content="Abrir el razonamiento paso a paso" shortcut={['↵']}>
          <Button size="sm" variant="ghost" leadingIcon={<ListTree aria-hidden />} onClick={() => actions.open(row)}>
            Ver razonamiento
          </Button>
        </Tooltip>
        {similarCount > 0 && (
          <Button size="sm" variant="ghost" className={styles.similar} leadingIcon={<CopyCheck aria-hidden />} onClick={() => actions.similar(row)}>
            Aplicar a similares · {similarCount}
          </Button>
        )}
      </div>
    </div>
  )
}
