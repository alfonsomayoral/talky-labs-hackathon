// Score against golden as score.py computes it: total, per-task score with weight and sub-scores,
// and the trial-balance gap recorded vs after the delivered entries.
import { Fragment, useState } from 'react'
import clsx from 'clsx'
import { ChevronRight } from 'lucide-react'
import { Amount, Card, Mono } from '@/components'
import type { ScoreReport, TaskKey, TrialBalanceComparison } from '@/domain/types'
import { TASK_WEIGHTS } from '@/domain/types'
import { formatNumber, formatPercent } from '@/lib/format'
import { PIPELINE, TASK_META } from '@/domain/catalog/labels'
import s from './ScoreCard.module.css'

type Row = TaskKey | 'trial_balance'
const ROWS: Row[] = [...PIPELINE, 'trial_balance']
const label = (r: Row) => (r === 'trial_balance' ? 'Balance' : TASK_META[r].label)

type Kind = 'ratio' | 'count' | 'eur' | 'ratios'
const DETAILS: Record<string, { label: string; kind: Kind }> = {
  decision_macro_f1: { label: 'F1 macro de la decisión', kind: 'ratio' },
  header: { label: 'Cabecera', kind: 'ratio' },
  coding: { label: 'Imputación de líneas', kind: 'ratio' },
  po_match: { label: 'Casación con pedido', kind: 'ratio' },
  journal_entry: { label: 'Asiento', kind: 'ratio' },
  reasons: { label: 'Motivos y duplicado', kind: 'ratio' },
  payee_and_block: { label: 'Beneficiario y bloqueo', kind: 'ratio' },
  per_decision_f1: { label: 'F1 por decisión', kind: 'ratios' },
  documents: { label: 'Documentos', kind: 'count' },
  answered: { label: 'Respondidos', kind: 'count' },
  items: { label: 'Partidas', kind: 'count' },
  receipts: { label: 'Cobros', kind: 'count' },
  fully_correct: { label: 'Exactos', kind: 'count' },
  per_account: { label: 'Por cuenta', kind: 'ratios' },
  differences: { label: 'Diferencias en golden', kind: 'count' },
  detected: { label: 'Detectadas', kind: 'count' },
  recall: { label: 'Exhaustividad', kind: 'ratio' },
  precision: { label: 'Precisión', kind: 'ratio' },
  abs_difference_eur: { label: 'Diferencia con el balance correcto', kind: 'eur' },
  recorded_vs_truth_eur: { label: 'Diferencia del registrado con el correcto', kind: 'eur' },
}

const pct = (v: unknown) => (typeof v === 'number' ? formatPercent(v, { decimals: 2 }) : '—')

function DetailValue({ value, kind }: { value: unknown; kind: Kind }) {
  if (kind === 'ratios' && value && typeof value === 'object')
    return (
      <span className={s.ratios}>
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <span key={k} className={s.ratio}>
            <Mono muted>{k}</Mono> <span className={clsx('tabular', typeof v === 'number' && v < 1 && s.low)}>{pct(v)}</span>
          </span>
        ))}
      </span>
    )
  if (typeof value !== 'number') return <Mono>{JSON.stringify(value)}</Mono>
  if (kind === 'count') return <span className="tabular">{formatNumber(value)}</span>
  if (kind === 'eur') return <Amount cents={Math.round(value * 100)} />
  return <span className={clsx('tabular', value < 1 && s.low)}>{pct(value)}</span>
}

function Details({ details }: { details: Record<string, unknown> }) {
  return (
    <dl className={s.details}>
      {Object.entries(details).map(([k, v]) => {
        const meta = DETAILS[k] ?? { label: k, kind: typeof v === 'object' ? 'ratios' : 'ratio' }
        return (
          <Fragment key={k}>
            <dt>{meta.label}</dt>
            <dd>
              <DetailValue value={v} kind={meta.kind} />
            </dd>
          </Fragment>
        )
      })}
    </dl>
  )
}

export function ScoreCard({ score, trialBalance }: { score: ScoreReport; trialBalance: TrialBalanceComparison | null }) {
  const [open, setOpen] = useState<Row | null>(null)
  const tb = score.tasks.trial_balance.details
  const gapRecorded = trialBalance?.gapRecorded ?? (typeof tb.recorded_vs_truth_eur === 'number' ? Math.round(tb.recorded_vs_truth_eur * 100) : null)
  const gapAfter = trialBalance?.gapAfter ?? (typeof tb.abs_difference_eur === 'number' ? Math.round(tb.abs_difference_eur * 100) : null)

  return (
    <Card title="Nota frente a golden" description="Mismo cálculo que score.py: nota por tarea ponderada, de 0 a 100.">
      <div className={s.layout}>
        <div className={s.total}>
          <span className={clsx(s.totalValue, 'tabular')}>{formatNumber(score.total, { decimals: 2 })}</span>
          <span className={s.totalOf}>de 100</span>
          {gapRecorded !== null && gapAfter !== null && (
            <div className={s.gap}>
              <div className={s.gapLabel}>Hueco del balance</div>
              <div className={s.gapRow}>
                <span>Registrado</span>
                <Amount cents={gapRecorded} compact />
              </div>
              <div className={s.gapRow}>
                <span>Tras la entrega</span>
                <Amount cents={gapAfter} compact />
              </div>
            </div>
          )}
        </div>
        <table className={s.table}>
          <thead>
            <tr>
              <th>Tarea</th>
              <th className={s.num}>Peso</th>
              <th className={s.num}>Nota</th>
              <th className={s.num}>Aporta</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map((r) => {
              const t = score.tasks[r]
              const expanded = open === r
              return (
                <Fragment key={r}>
                  <tr className={s.taskRow}>
                    <td>
                      <button type="button" className={s.toggle} aria-expanded={expanded} onClick={() => setOpen(expanded ? null : r)}>
                        <ChevronRight aria-hidden className={clsx(s.chevron, expanded && s.open)} />
                        {label(r)}
                      </button>
                    </td>
                    <td className={s.num}>{formatPercent(TASK_WEIGHTS[r])}</td>
                    <td className={clsx(s.num, t.score < 1 && s.low)}>{pct(t.score)}</td>
                    <td className={s.num}>{formatNumber(TASK_WEIGHTS[r] * t.score * 100, { decimals: 2 })}</td>
                  </tr>
                  {expanded && (
                    <tr>
                      <td colSpan={4} className={s.detailCell}>
                        <Details details={t.details} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              )
            })}
          </tbody>
        </table>
      </div>
    </Card>
  )
}
