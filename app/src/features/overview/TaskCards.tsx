import { Link } from 'react-router'
import { ArrowRight } from 'lucide-react'
import { Badge, Card, Section } from '@/components'
import type { DerivedRun, TaskKey } from '@/domain/types'
import { TASK_WEIGHTS } from '@/domain/types'
import { formatNumber, formatPercent } from '@/lib/format'
import { eur, outcomeBreakdown, PIPELINE, scoreFacts, TASK_META, type BalanceSummary } from './model'
import styles from './Overview.module.css'

const TOP_OUTCOMES = 4

export function TaskCards({ data, balance }: { data: DerivedRun; balance: BalanceSummary | null }) {
  return (
    <Section title="Por tarea" description="Peso en la nota, partidas y en qué acabó cada una.">
      <div className={styles.taskGrid}>
        {PIPELINE.map((task) => (
          <TaskCard key={task} task={task} data={data} />
        ))}
        <BalanceCard balance={balance} score={data.score?.tasks.trial_balance.score ?? null} />
      </div>
    </Section>
  )
}

function TaskCard({ task, data }: { task: TaskKey; data: DerivedRun }) {
  const outcomes = outcomeBreakdown(data.items, task)
  // A single leftover outcome is shown instead of «1 resultado más».
  const cut = outcomes.length > TOP_OUTCOMES + 1 ? TOP_OUTCOMES : outcomes.length
  const shown = outcomes.slice(0, cut)
  const rest = outcomes.slice(cut)
  const score = data.score?.tasks[task]
  const items = data.stats.byTask[task].items
  const matched = task === 'bank_rec' ? (outcomes.find((o) => o.outcome === 'MATCH')?.count ?? 0) : null
  return (
    <Card title={TASK_META[task].label} actions={<Badge variant="outline">Peso {formatPercent(TASK_WEIGHTS[task])}</Badge>} className={styles.taskCard}>
      <div className={styles.taskBody}>
        <p className={styles.taskHeadline}>
          <span className={styles.taskNumber}>{formatNumber(items)}</span> partidas
          {matched !== null && (
            <span className={styles.taskAside}>
              {formatNumber(matched)} casadas · {formatNumber(items - matched)} sin casar o ajustes
            </span>
          )}
        </p>
        {shown.length > 0 && (
          <ul className={styles.outcomes}>
            {shown.map((o) => (
              <li key={o.outcome} title={o.outcome}>
                <span className={styles.outcomeLabel}>{o.label}</span>
                <span className="tabular">{formatNumber(o.count)}</span>
              </li>
            ))}
            {rest.length > 0 && (
              <li className={styles.outcomeRest}>
                <span>
                  {rest.length} {rest.length === 1 ? 'resultado más' : 'resultados más'}
                </span>
                <span className="tabular">{formatNumber(rest.reduce((s, o) => s + o.count, 0))}</span>
              </li>
            )}
          </ul>
        )}
        {score && (
          <dl className={styles.facts}>
            <div className={styles.factMain}>
              <dt>Nota</dt>
              <dd className="tabular">{formatPercent(score.score)}</dd>
            </div>
            {scoreFacts(task, score.details).map((f) => (
              <div key={f.label}>
                <dt>{f.label}</dt>
                <dd className="tabular">{f.value}</dd>
              </div>
            ))}
          </dl>
        )}
        <Link to={TASK_META[task].route} className={styles.cardLink}>
          Ver tarea <ArrowRight aria-hidden />
        </Link>
      </div>
    </Card>
  )
}

function BalanceCard({ balance, score }: { balance: BalanceSummary | null; score: number | null }) {
  return (
    <Card title="Balance" actions={<Badge variant="outline">Peso {formatPercent(TASK_WEIGHTS.trial_balance)}</Badge>} className={styles.taskCard}>
      <div className={styles.taskBody}>
        {!balance ? (
          <p className={styles.muted}>Sumando el diario…</p>
        ) : (
          <>
            {balance.score != null ? (
              <p className={styles.taskHeadline}>
                <span className={styles.taskNumber}>{formatPercent(balance.score)}</span> del hueco cerrado
                <span className={styles.taskAside}>
                  Registrado {eur(balance.gapRecordedEur)} → después {eur(balance.gapAfterEur)}
                </span>
              </p>
            ) : (
              <p className={styles.taskHeadline}>
                Sin golden no hay balance correcto
                <span className={styles.taskAside}>Movimiento de cada tarea sobre el registrado</span>
              </p>
            )}
            <ul className={styles.outcomes}>
              {balance.movement.slice(0, TOP_OUTCOMES).map((m) => (
                <li key={m.task}>
                  <span className={styles.outcomeLabel}>{TASK_META[m.task].label}</span>
                  <span className="tabular">{eur(m.amountEur)}</span>
                </li>
              ))}
            </ul>
          </>
        )}
        {score != null && (
          <dl className={styles.facts}>
            <div className={styles.factMain}>
              <dt>Nota</dt>
              <dd className="tabular">{formatPercent(score)}</dd>
            </div>
          </dl>
        )}
        <Link to="/balance" className={styles.cardLink}>
          Ver balance <ArrowRight aria-hidden />
        </Link>
      </div>
    </Card>
  )
}
