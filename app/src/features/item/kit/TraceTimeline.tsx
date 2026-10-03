import { useMemo } from 'react'
import clsx from 'clsx'
import { Check, ListChecks, Sparkles, X } from 'lucide-react'
import type { AgentEvent, EvidenceRef, ModelCall } from '@/domain/types'
import { ConfidenceBand, Mono, Tooltip } from '@/components'
import { formatDuration, formatPercent } from '@/lib/format'
import { EVENT_KIND_META, evidenceKey, evidenceLabel } from './labels'
import { PolicyCascade } from './PolicyCascade'
import { reasoningSteps, type ReasoningStep } from './reasoning'
import styles from './TraceTimeline.module.css'

export interface TraceTimelineProps {
  /** Steps from `reasoningSteps(events, cascade)`; or pass raw `events`. */
  steps?: ReasoningStep[]
  events?: AgentEvent[]
  /** Click on an evidence chip (e.g. open it in the Evidencia tab). */
  onEvidence?: (ref: EvidenceRef, key: string) => void
  className?: string
}

const RESULT_LABEL = { PASS: 'Correcto', FAIL: 'Falla', INFO: '' } as const

/** The steps of an item in order: kind icon, ✓/✗, summary, § chip, evidence, model and confidence. */
export function TraceTimeline({ steps, events, onEvidence, className }: TraceTimelineProps) {
  const list = useMemo(() => steps ?? reasoningSteps(events ?? []), [steps, events])
  if (!list.length) return null
  return (
    <ol className={clsx(styles.timeline, className)}>
      {list.map((s) => (
        <TimelineStep key={s.key} step={s} onEvidence={onEvidence} />
      ))}
    </ol>
  )
}

function TimelineStep({ step, onEvidence }: { step: ReasoningStep; onEvidence?: TraceTimelineProps['onEvidence'] }) {
  const meta = step.kind === 'CASCADE' ? { label: 'Cascada de la política', icon: ListChecks } : EVENT_KIND_META[step.kind]
  const Icon = meta?.icon ?? ListChecks
  const Marker = step.result === 'PASS' ? Check : step.result === 'FAIL' ? X : null
  return (
    <li className={styles.step} data-result={step.result}>
      <span className={styles.rail} aria-hidden>
        <span className={styles.node}>
          <Icon className={styles.kindIcon} />
        </span>
      </span>
      <div className={styles.body}>
        <div className={styles.titleRow}>
          <span className={styles.kind}>{meta?.label ?? step.kind}</span>
          {Marker && (
            <span className={styles.result}>
              <Marker aria-hidden className={styles.resultIcon} />
              {RESULT_LABEL[step.result]}
            </span>
          )}
        </div>
        <p className={styles.title}>{step.title}</p>
        {step.cascade && <PolicyCascade checks={step.cascade} className={styles.cascade} />}
        <StepMeta step={step} onEvidence={onEvidence} />
      </div>
    </li>
  )
}

function StepMeta({ step, onEvidence }: { step: ReasoningStep; onEvidence?: TraceTimelineProps['onEvidence'] }) {
  const evidence = uniqueEvidence(step.evidence)
  if (!step.policyRef && !evidence.length && !step.model && step.confidence === null && step.durationMs === null) return null
  return (
    <div className={styles.meta}>
      {step.policyRef && <span className={styles.policy}>{step.policyRef}</span>}
      {evidence.map((ref) => {
        const key = evidenceKey(ref)
        const label = evidenceLabel(ref)
        return onEvidence ? (
          <button key={key} type="button" className={styles.evidence} onClick={() => onEvidence(ref, key)} title="Ver en Evidencia">
            {label}
          </button>
        ) : (
          <span key={key} className={styles.evidence}>
            {label}
          </span>
        )
      })}
      {step.model && <ModelChip model={step.model} />}
      {step.confidence !== null && <ConfidenceBand value={step.confidence} showValue />}
      {step.durationMs !== null && <span className={styles.duration}>{formatDuration(step.durationMs)}</span>}
    </div>
  )
}

function uniqueEvidence(refs: EvidenceRef[]): EvidenceRef[] {
  const seen = new Set<string>()
  return refs.filter((r) => {
    const k = evidenceKey(r)
    if (seen.has(k)) return false
    seen.add(k)
    return true
  })
}

export function ModelChip({ model }: { model: ModelCall }) {
  const probs = Object.entries(model.probabilities ?? {}).sort((a, b) => b[1] - a[1])
  const top = model.answer && model.probabilities?.[model.answer] !== undefined ? model.probabilities[model.answer] : probs[0]?.[1]
  const tip = (
    <span className={styles.modelTip}>
      <span>
        {model.provider} · {model.name}
        {model.question ? ` · ${model.question}` : ''}
      </span>
      {probs.slice(0, 5).map(([k, p]) => (
        <span key={k} className={styles.prob}>
          <Mono>{k}</Mono> {formatPercent(p, { decimals: 0 })}
        </span>
      ))}
    </span>
  )
  return (
    <Tooltip content={tip}>
      <span className={styles.model} tabIndex={0}>
        <Sparkles aria-hidden className={styles.modelIcon} />
        {model.name}
        {model.answer && (
          <>
            {' → '}
            <Mono>{model.answer}</Mono>
          </>
        )}
        {top !== undefined && <span className={styles.modelProb}>{formatPercent(top, { decimals: 0 })}</span>}
      </span>
    </Tooltip>
  )
}
