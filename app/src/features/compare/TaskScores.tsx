// Sub-scores per task in pipeline order, with weight, score and what each contributes to the total.
// A task filters the list below; the trial balance is scored as a whole and has no items.
import clsx from 'clsx'
import type { TaskKey } from '@/domain/types'
import { TASK_META } from '@/domain/catalog/labels'
import { formatNumber, formatPercent } from '@/lib/format'
import type { TaskSummary } from './model'
import styles from './TaskScores.module.css'

export interface TaskScoresProps {
  total: number
  summaries: TaskSummary[]
  selected: TaskKey | null
  onSelect: (task: TaskKey | null) => void
}

const points = (v: number) => formatNumber(v, { decimals: 2 })

export function TaskScores({ total, summaries, selected, onSelect }: TaskScoresProps) {
  const lost = summaries.reduce((s, r) => s + r.lost, 0)
  return (
    <section className={styles.strip} aria-label="Nota por tarea">
      <div className={styles.total}>
        <span className={styles.label}>Nota</span>
        <span className={clsx(styles.totalValue, 'tabular')}>{points(total)}</span>
        <span className={styles.meta}>de 100 · pierde {points(lost)}</span>
      </div>
      {summaries.map((r) => {
        const body = (
          <>
            <span className={styles.head}>
              <span className={styles.label}>{r.task === 'trial_balance' ? 'Balance' : TASK_META[r.task].label}</span>
              <span className={clsx(styles.weight, 'tabular')} title="Peso en la nota total">
                {formatPercent(r.weight)}
              </span>
            </span>
            <span className={clsx(styles.value, 'tabular', r.score < 1 && styles.low)}>{formatPercent(r.score, { decimals: 2 })}</span>
            <span className={clsx(styles.meta, 'tabular')}>
              Aporta {points(r.contributes)} de {formatNumber(r.weight * 100)}
            </span>
            <span className={clsx(styles.meta, 'tabular')}>
              {r.differing === null ? 'Se puntúa entero' : r.differing === 0 ? 'Sin diferencias' : `${formatNumber(r.differing)} ${r.differing === 1 ? 'partida difiere' : 'partidas difieren'}`}
            </span>
          </>
        )
        if (r.task === 'trial_balance') return <div key={r.task} className={styles.card}>{body}</div>
        const task = r.task
        const active = selected === task
        return (
          <button key={task} type="button" className={clsx(styles.card, styles.button, active && styles.active)} aria-pressed={active} onClick={() => onSelect(active ? null : task)}>
            {body}
          </button>
        )
      })}
    </section>
  )
}
