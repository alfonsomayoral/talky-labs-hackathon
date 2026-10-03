// `/coste` Coste y ejecución: ¿qué ha costado? Models and tokens, time per task and confidence calibration.
import { useMemo } from 'react'
import { Cpu, Timer } from 'lucide-react'
import { EmptyState, Metric, Mono, Page, PageHeader, QueryState, Section } from '@/components'
import type { DerivedRun, RunBundle } from '@/domain/types'
import { useActiveRun, useDerivedRun } from '@/engine'
import { formatDateTime, formatDuration, formatMoney, formatNumber, formatPercent } from '@/lib/format'
import { Calibration } from './Calibration'
import { costSummary, taskTimeline, TASK_LABEL, type CostSummary, type Timeline } from './model'
import styles from './CostPage.module.css'

const usd = (value: number | null | undefined) => (value == null ? '—' : formatMoney(Math.round(value * 100), 'USD'))

export default function CostPage() {
  const { status, data, error } = useDerivedRun()
  const run = useActiveRun()
  return (
    <Page>
      <PageHeader title="Coste y ejecución" subtitle={run ? run.label : 'Modelos, tokens, tiempo por tarea y fiabilidad de las confianzas'} />
      <QueryState status={status} error={error}>
        {() => data && run && <Cost data={data} run={run} />}
      </QueryState>
    </Page>
  )
}

function Cost({ data, run }: { data: DerivedRun; run: RunBundle }) {
  const cost = useMemo(() => costSummary(run.manifest), [run.manifest])
  const timeline = useMemo(() => taskTimeline(run.manifest, run.events), [run.manifest, run.events])
  const count = (n: number) => (cost.models.length ? formatNumber(n) : '—')
  return (
    <>
      <section className={styles.vitals} aria-label="Indicadores de coste">
        <Metric label="Coste" value={usd(cost.costUsd)} comparison={costNote(run, cost)} hint="Coste estimado de las llamadas a modelos, según el manifiesto de la ejecución." />
        <Metric
          label="Duración"
          value={formatDuration(cost.runtimeMs)}
          comparison={run.manifest?.started_at ? `desde ${formatDateTime(run.manifest.started_at)}` : 'Sin marca de inicio'}
        />
        <Metric label="Llamadas a modelos" value={count(cost.calls)} comparison={cost.models.length === 1 ? '1 modelo' : `${cost.models.length} modelos`} />
        <Metric
          label="Tokens"
          value={count(cost.inputTokens + cost.outputTokens)}
          comparison={cost.models.length ? `${formatNumber(cost.inputTokens)} entrada · ${formatNumber(cost.outputTokens)} salida` : 'Sin llamadas registradas'}
        />
      </section>
      <Section title="Modelos" description="Llamadas, tokens y coste por modelo, desde manifest.json.">
        <Models run={run} cost={cost} />
      </Section>
      <Section title="Duración por tarea" description={timeline ? timelineSource(timeline) : 'Cuánto tarda cada tarea del cierre.'}>
        {timeline ? (
          <Gantt timeline={timeline} />
        ) : (
          <EmptyState
            size="sm"
            icon={<Timer />}
            title="Esta ejecución no trae tiempos por tarea"
            description="Aparecen cuando el manifiesto incluye tasks con started_at y finished_at, o cuando trace/events.jsonl trae marcas de tiempo reales."
          />
        )}
      </Section>
      <Calibration data={data} run={run} />
    </>
  )
}

function costNote(run: RunBundle, cost: CostSummary): string {
  if (!run.manifest) return 'Sin manifiesto'
  if (run.manifest.cost_status === 'no_llm') return 'Sin modelos: solo reglas'
  if (cost.costUsd == null) return 'El manifiesto no indica coste'
  return run.manifest.cost_status === 'partial' ? 'Estimación parcial' : 'Estimado'
}

const timelineSource = (t: Timeline) =>
  t.source === 'manifest' ? 'Inicio y fin de cada tarea según manifest.json.' : 'Primer y último evento de cada tarea en trace/events.jsonl.'

function Models({ run, cost }: { run: RunBundle; cost: CostSummary }) {
  if (!cost.models.length)
    return (
      <EmptyState
        size="sm"
        icon={<Cpu />}
        title={run.manifest ? 'El manifiesto no registra llamadas a modelos' : 'Esta ejecución no trae manifiesto'}
        description={
          run.source === 'golden'
            ? 'La referencia (golden) es la solución del reto: no la produjo ningún modelo.'
            : 'El backend escribe el informe de ejecución (outputs/runs/<uuid>.json); inclúyelo en el paquete como manifest.json.'
        }
      />
    )
  const totalCost = cost.costUsd ?? 0
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Modelo</th>
            <th>Proveedor</th>
            <th className={styles.num}>Llamadas</th>
            <th className={styles.num}>Tokens de entrada</th>
            <th className={styles.num}>Tokens de salida</th>
            <th className={styles.num}>Coste</th>
            <th className={styles.shareHead}>Parte del coste</th>
          </tr>
        </thead>
        <tbody>
          {cost.models.map((m) => {
            const share = totalCost > 0 ? m.cost_usd / totalCost : 0
            return (
              <tr key={`${m.provider}/${m.name}`}>
                <td>
                  <Mono>{m.name}</Mono>
                </td>
                <td>{m.provider}</td>
                <td className={styles.num}>{formatNumber(m.calls)}</td>
                <td className={styles.num}>{formatNumber(m.input_tokens)}</td>
                <td className={styles.num}>{formatNumber(m.output_tokens)}</td>
                <td className={styles.num}>{usd(m.cost_usd)}</td>
                <td>
                  <div className={styles.share}>
                    <span className={styles.shareTrack}>
                      <span className={styles.shareFill} style={{ width: `${share * 100}%` }} />
                    </span>
                    <span className="tabular">{formatPercent(share)}</span>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

const TICKS = [0, 0.25, 0.5, 0.75, 1]

function Gantt({ timeline }: { timeline: Timeline }) {
  const pct = (ms: number) => `${(ms / timeline.total) * 100}%`
  return (
    <div className={styles.gantt} role="table" aria-label="Duración por tarea">
      {timeline.spans.map((s) => (
        <div key={s.task} className={styles.ganttRow} role="row">
          <span className={styles.ganttLabel} role="rowheader">
            {TASK_LABEL[s.task]}
          </span>
          <span className={styles.ganttTrack} role="cell">
            <span className={styles.ganttBar} style={{ left: pct(s.start), width: `max(2px, ${pct(s.end - s.start)})` }} />
          </span>
          <span className={styles.ganttValue} role="cell">
            {formatDuration(s.end - s.start)}
          </span>
        </div>
      ))}
      <div className={styles.ganttRow} aria-hidden>
        <span />
        <span className={styles.ganttAxis}>
          {TICKS.map((t) => (
            <span key={t} style={{ left: `${t * 100}%` }}>
              {formatDuration(t * timeline.total)}
            </span>
          ))}
        </span>
        <span />
      </div>
    </div>
  )
}
