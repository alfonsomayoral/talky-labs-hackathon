// Reliability curve and threshold slider, when the run's DECIDE events carry confidence.
import { useMemo, useState } from 'react'
import { Gauge } from 'lucide-react'
import { CONFIDENCE_THRESHOLDS, EmptyState, Metric, Mono, Section } from '@/components'
import type { DerivedRun, RunBundle } from '@/domain/types'
import { formatNumber, formatPercent } from '@/lib/format'
import { useOpenItem } from '@/shell/useOpenItem'
import { confidencePoints, expectedCalibrationError, reliabilityBins, thresholdStats, TASK_LABEL, type ConfidencePoint, type ReliabilityBin } from './model'
import styles from './CostPage.module.css'

const LEAK_LIMIT = 8

export function Calibration({ data, run }: { data: DerivedRun; run: RunBundle }) {
  const points = useMemo(() => confidencePoints(data.items, data.score?.perItem ?? null), [data.items, data.score])
  const bins = useMemo(() => reliabilityBins(points), [points])
  const [threshold, setThreshold] = useState<number>(CONFIDENCE_THRESHOLDS.high)
  const stats = useMemo(() => thresholdStats(points, threshold), [points, threshold])
  const openItem = useOpenItem()

  if (!points.length)
    return (
      <Section title="Calibración" description="¿Acierta el agente tanto como dice?">
        <EmptyState size="sm" icon={<Gauge />} title="Esta ejecución no trae confianza" description={noConfidenceReason(run, data)} />
      </Section>
    )

  const hasGolden = points.some((p) => p.correct !== null)
  const ece = expectedCalibrationError(bins)
  const leaks = points.filter((p) => p.p >= threshold && p.correct === false).sort((a, b) => a.p - b.p)

  return (
    <Section
      title="Calibración"
      count={points.length}
      description={
        hasGolden
          ? 'Confianza declarada en el evento DECIDE frente al acierto real contra golden. Sobre la diagonal, el agente acierta lo que dice.'
          : 'Sin golden no se puede medir el acierto: se muestra cómo se reparten las confianzas.'
      }
    >
      <div className={styles.calibration}>
        <ReliabilityChart bins={bins} threshold={threshold} hasGolden={hasGolden} />
        <div className={styles.threshold}>
          <label className={styles.sliderLabel}>
            <span>
              Umbral de autonomía <strong className="tabular">{formatPercent(threshold, { decimals: 0 })}</strong>
            </span>
            <input
              type="range"
              min={0.5}
              max={1}
              step={0.01}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className={styles.slider}
            />
          </label>
          <div className={styles.thresholdMetrics}>
            <Metric label="Las cierra el agente" value={formatNumber(stats.auto)} comparison={`${formatPercent(stats.coverage)} de ${formatNumber(stats.total)}`} />
            <Metric label="A una persona" value={formatNumber(stats.toHuman)} comparison="por debajo del umbral" />
            <Metric
              label="Errores esperados"
              value={formatNumber(stats.expectedErrors, { decimals: 1 })}
              comparison="Σ (1 − p) de las automáticas"
              hint="Errores que el propio agente espera dejar pasar si cierra solo lo que supera el umbral."
            />
            <Metric
              label="Errores reales"
              value={stats.actualErrors == null ? '—' : formatNumber(stats.actualErrors)}
              comparison={stats.accuracy == null ? 'Sin golden' : `acierto ${formatPercent(stats.accuracy)}`}
              hint="Partidas automáticas que no coinciden con golden."
            />
          </div>
          {ece != null && (
            <p className={styles.ece}>
              Error de calibración esperado (ECE): <strong className="tabular">{formatPercent(ece, { decimals: 1 })}</strong>
            </p>
          )}
          {leaks.length > 0 && (
            <div className={styles.leaks}>
              <h3 className={styles.leaksTitle}>Errores que pasarían el umbral ({formatNumber(leaks.length)})</h3>
              <ul className={styles.leakList}>
                {leaks.slice(0, LEAK_LIMIT).map((p) => (
                  <Leak key={p.item} point={p} onOpen={() => openItem(p.item)} />
                ))}
              </ul>
            </div>
          )}
        </div>
      </div>
    </Section>
  )
}

function Leak({ point, onOpen }: { point: ConfidencePoint; onOpen: () => void }) {
  return (
    <li>
      <button type="button" className={styles.leak} onClick={onOpen}>
        <Mono>{point.item.slice(point.item.indexOf(':') + 1)}</Mono>
        <span className={styles.leakTask}>{TASK_LABEL[point.task]}</span>
        <span className="tabular">{formatPercent(point.p)}</span>
      </button>
    </li>
  )
}

function noConfidenceReason(run: RunBundle, data: DerivedRun): string {
  if (run.source === 'golden') return 'La referencia (golden) es la solución del reto: no tiene confianzas que calibrar.'
  if (data.eventsSynthesized) return 'La curva de fiabilidad aparece cuando el paquete trae trace/events.jsonl con confidence en los eventos DECIDE.'
  return 'Los eventos DECIDE de trace/events.jsonl no traen el campo confidence.'
}

// ---------------------------------------------------------------- chart (SVG)

const W = 360
const H = 260
const PAD = { top: 12, right: 12, bottom: 64, left: 40 }
const PLOT_W = W - PAD.left - PAD.right
const PLOT_H = H - PAD.top - PAD.bottom
const HIST_H = 28
const x = (v: number) => PAD.left + v * PLOT_W
const y = (v: number) => PAD.top + (1 - v) * PLOT_H

function ReliabilityChart({ bins, threshold, hasGolden }: { bins: ReliabilityBin[]; threshold: number; hasGolden: boolean }) {
  const maxCount = Math.max(1, ...bins.map((b) => b.count))
  const curve = bins.filter((b) => b.accuracy !== null && b.meanP !== null)
  const histTop = H - HIST_H - 4
  return (
    <svg className={styles.chart} viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Curva de fiabilidad: confianza declarada frente a acierto real">
      {[0, 0.5, 1].map((v) => (
        <g key={v}>
          <line className={styles.grid} x1={x(0)} x2={x(1)} y1={y(v)} y2={y(v)} />
          <text className={styles.tick} x={PAD.left - 6} y={y(v)} textAnchor="end" dominantBaseline="middle">
            {formatPercent(v)}
          </text>
          <text className={styles.tick} x={x(v)} y={PAD.top + PLOT_H + 14} textAnchor="middle">
            {formatPercent(v)}
          </text>
        </g>
      ))}
      <text className={styles.axisLabel} x={x(0.5)} y={PAD.top + PLOT_H + 28} textAnchor="middle">
        Confianza declarada
      </text>
      <rect className={styles.below} x={x(0)} y={PAD.top} width={x(threshold) - x(0)} height={PLOT_H} />
      <line className={styles.thresholdLine} x1={x(threshold)} x2={x(threshold)} y1={PAD.top} y2={PAD.top + PLOT_H} />
      {hasGolden && (
        <>
          <line className={styles.diagonal} x1={x(0)} y1={y(0)} x2={x(1)} y2={y(1)} />
          <polyline className={styles.curve} points={curve.map((b) => `${x(b.meanP!)},${y(b.accuracy!)}`).join(' ')} />
          {curve.map((b) => (
            <circle key={b.lo} className={styles.dot} cx={x(b.meanP!)} cy={y(b.accuracy!)} r={3 + 3 * Math.sqrt(b.known / maxCount)}>
              <title>{`${formatPercent(b.lo)}–${formatPercent(b.hi)}: ${b.known} partidas, acierto ${formatPercent(b.accuracy)}`}</title>
            </circle>
          ))}
        </>
      )}
      {bins.map((b) => {
        const h = (b.count / maxCount) * HIST_H
        return (
          <rect key={b.lo} className={styles.histBar} x={x(b.lo) + 1} width={Math.max(0, x(b.hi) - x(b.lo) - 2)} y={histTop + HIST_H - h} height={h}>
            <title>{`${formatPercent(b.lo)}–${formatPercent(b.hi)}: ${b.count} partidas`}</title>
          </rect>
        )
      })}
      {!hasGolden && (
        <text className={styles.axisLabel} x={x(0.5)} y={y(0.5)} textAnchor="middle">
          Sin golden: solo distribución
        </text>
      )}
    </svg>
  )
}
