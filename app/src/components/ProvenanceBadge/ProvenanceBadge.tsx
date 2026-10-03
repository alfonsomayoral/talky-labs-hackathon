import { BookMarked, History, Sparkles, User, Workflow, type LucideIcon } from 'lucide-react'
import type { Provenance } from '@/domain/types'
import { Badge } from '../Badge/Badge'
import { PROVENANCE, toneColor } from '../status'

const ICONS: Record<Provenance, LucideIcon> = {
  RULE: Workflow,
  HISTORY: History,
  MODEL: Sparkles,
  HUMAN: User,
  REFERENCE: BookMarked,
}

const DESCRIPTIONS: Record<Provenance, string> = {
  RULE: 'Decidido por una regla determinista de la política',
  HISTORY: 'Decidido por precedente histórico',
  MODEL: 'Decidido con ayuda de un modelo',
  HUMAN: 'Corregido por una persona',
  REFERENCE: 'Tomado de la solución de referencia',
}

export interface ProvenanceBadgeProps {
  provenance: Provenance
  /** Icon only (label stays as tooltip and accessible name). */
  compact?: boolean
  className?: string
}

/** Where a decision came from: Regla, Histórico, Modelo, Humano, Referencia. */
export function ProvenanceBadge({ provenance, compact, className }: ProvenanceBadgeProps) {
  const meta = PROVENANCE[provenance]
  const Icon = ICONS[provenance]
  const icon = <Icon aria-hidden style={{ color: toneColor(meta.tone) }} />
  if (compact) {
    return (
      <span className={className} role="img" aria-label={meta.label} title={`${meta.label} · ${DESCRIPTIONS[provenance]}`} style={{ display: 'inline-flex' }}>
        {icon}
      </span>
    )
  }
  return (
    <Badge variant="outline" tone={meta.tone} icon={icon} className={className} title={DESCRIPTIONS[provenance]}>
      {meta.label}
    </Badge>
  )
}
