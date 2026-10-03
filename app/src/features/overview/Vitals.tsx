import { Metric } from '@/components'
import type { Priority, RunManifest, RunStats } from '@/domain/types'
import { formatDuration, formatMoney, formatNumber, formatPercent } from '@/lib/format'
import { eur, TASK_META, type AttentionSummary, type BalanceSummary } from './model'
import styles from './Overview.module.css'

const PRIORITIES: Priority[] = ['P0', 'P1', 'P2', 'P3']

interface VitalsProps {
  stats: RunStats
  attention: AttentionSummary
  /** Null while the journal is summed. */
  balance: BalanceSummary | null
  scoreTotal: number | null
  manifest: RunManifest | null
}

export function Vitals({ stats, attention, balance, scoreTotal, manifest }: VitalsProps) {
  const auto = stats.byStatus.AUTO ?? 0
  const byPriority = stats.attention.byPriority
  const cost = manifest?.cost_usd_total
  const runtime = manifest?.runtime_s
  return (
    <section className={styles.vitals} aria-label="Indicadores del cierre">
      <Metric
        label="Autonomía"
        value={formatPercent(stats.items ? auto / stats.items : null)}
        comparison={`${formatNumber(auto)} de ${formatNumber(stats.items)} partidas`}
        hint="Partidas resueltas sin intervención: ni bloqueadas, ni en atención, ni abiertas."
      />
      <Metric
        label="En atención"
        value={formatNumber(attention.count)}
        delta={eur(attention.impactEur)}
        comparison={PRIORITIES.filter((p) => byPriority[p])
          .map((p) => `${p} ${byPriority[p]}`)
          .join(' · ')}
        hint="Partidas que necesitan a una persona e importe afectado, en EUR (3100 al tipo de cierre)."
      />
      {balance?.score != null ? (
        <Metric
          label="Hueco del balance cerrado"
          value={formatPercent(balance.score)}
          comparison={`${eur(balance.gapRecordedEur)} → ${eur(balance.gapAfterEur)}`}
          hint="Parte de la diferencia entre el balance registrado y el correcto que cierran los asientos entregados, como en score.py. Importes en EUR."
        />
      ) : (
        <Metric
          label="Movimiento del balance"
          loading={!balance}
          value={balance ? eur(balance.movement.reduce((s, m) => s + m.amountEur, 0)) : ''}
          comparison={balance?.movement
            .slice(0, 2)
            .map((m) => `${TASK_META[m.task].label} ${eur(m.amountEur)}`)
            .join(' · ')}
          hint="Sin golden no se conoce el balance correcto: se muestra cuánto mueve el balance cada tarea (Σ|movimiento|, en EUR)."
        />
      )}
      <Metric
        label="Nota"
        value={scoreTotal != null ? formatNumber(scoreTotal, { decimals: 2 }) : '—'}
        comparison={scoreTotal != null ? 'sobre 100, como score.py' : 'Sin golden no hay nota'}
        hint="Nota ponderada de las seis tareas y el balance, calculada en la app con el mismo método que score.py."
      />
      <Metric
        label="Coste y tiempo"
        value={cost != null ? formatMoney(Math.round(cost * 100), 'USD') : '—'}
        comparison={runtime != null ? formatDuration(runtime * 1000) : manifest ? 'Sin duración' : 'Sin manifiesto'}
        hint="Coste de los modelos y duración del cierre, según manifest.json."
      />
    </section>
  )
}
