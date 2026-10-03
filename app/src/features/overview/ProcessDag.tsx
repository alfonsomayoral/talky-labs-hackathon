import { Link } from 'react-router'
import clsx from 'clsx'
import { ProgressBar, Section, StatusDot, statusSegments } from '@/components'
import type { DerivedRun, RunBundle } from '@/domain/types'
import { formatNumber, formatPercent } from '@/lib/format'
import { PIPELINE, TASK_META, type AttentionSummary } from './model'
import styles from './Overview.module.css'

interface ProcessDagProps {
  data: DerivedRun
  run: RunBundle
  attention: AttentionSummary
}

/** The six tasks in execution order; each node opens its task page. */
export function ProcessDag({ data, run, attention }: ProcessDagProps) {
  return (
    <Section title="Proceso del cierre" description="Las tareas en el orden en que se ejecutan. AP va primero: sus asientos alimentan bancos, cobros y cierre.">
      <ol className={styles.dag}>
        {PIPELINE.map((task, i) => {
          const t = data.stats.byTask[task]
          const meta = TASK_META[task]
          const score = data.score?.tasks[task].score
          const pending = attention.byTask[task]
          return (
            <li key={task} className={styles.dagStep}>
              <Link to={meta.route} className={clsx(styles.dagNode, i === 0 && styles.dagFirst)}>
                <span className={styles.dagHead}>
                  <span className={styles.dagOrder}>{i + 1}</span>
                  <span className={styles.dagLabel}>{meta.label}</span>
                </span>
                {i === 0 && <span className={styles.dagTag}>Primera dependencia</span>}
                {run.present[task] ? (
                  <span className={styles.dagCount}>
                    <span className="tabular">{formatNumber(t.items)}</span> partidas
                  </span>
                ) : (
                  <span className={styles.dagMissing}>Fichero ausente</span>
                )}
                <ProgressBar
                  size="sm"
                  label={`Estado de ${meta.label}`}
                  segments={statusSegments({ AUTO: t.auto, NEEDS_HUMAN: t.needsHuman, BLOCKED: t.blocked, OPEN: t.open })}
                />
                <span className={styles.dagFoot}>
                  <span className={styles.dagAttention}>
                    {pending > 0 && <StatusDot tone="warn" />}
                    {pending > 0 ? `${formatNumber(pending)} en atención` : 'Nada en atención'}
                  </span>
                  {score != null && <span className="tabular">Nota {formatPercent(score)}</span>}
                </span>
              </Link>
              {i < PIPELINE.length - 1 && (
                <svg className={styles.dagArrow} viewBox="0 0 28 12" aria-hidden>
                  <path d="M1 6h24" />
                  <path d="M21 2l4 4-4 4" />
                </svg>
              )}
            </li>
          )
        })}
      </ol>
    </Section>
  )
}
