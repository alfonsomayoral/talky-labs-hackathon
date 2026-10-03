// Shared colour vocabulary. Colour only carries meaning: brand (actions/selection) and status.
import type { ItemStatus, Priority, Provenance } from '@/domain/types'

export type Tone = 'neutral' | 'brand' | 'ok' | 'warn' | 'danger' | 'info'

export interface ToneMeta {
  label: string
  tone: Tone
}

export const ITEM_STATUS: Record<ItemStatus, ToneMeta> = {
  AUTO: { label: 'Resuelto', tone: 'ok' },
  NEEDS_HUMAN: { label: 'Necesita persona', tone: 'warn' },
  BLOCKED: { label: 'Bloqueado', tone: 'danger' },
  OPEN: { label: 'Abierto', tone: 'neutral' },
}

/** Display order for status groups and stacked bars. */
export const ITEM_STATUS_ORDER: ItemStatus[] = ['AUTO', 'NEEDS_HUMAN', 'BLOCKED', 'OPEN']

export const PRIORITY: Record<Priority, ToneMeta & { description: string }> = {
  P0: { label: 'P0', tone: 'danger', description: 'Urgente' },
  P1: { label: 'P1', tone: 'warn', description: 'Alta' },
  P2: { label: 'P2', tone: 'info', description: 'Media' },
  P3: { label: 'P3', tone: 'neutral', description: 'Baja' },
}

export const PROVENANCE: Record<Provenance, ToneMeta> = {
  RULE: { label: 'Regla', tone: 'info' },
  HISTORY: { label: 'Histórico', tone: 'neutral' },
  MODEL: { label: 'Modelo', tone: 'neutral' },
  HUMAN: { label: 'Humano', tone: 'brand' },
  REFERENCE: { label: 'Referencia', tone: 'neutral' },
}

/** CSS custom property with the solid colour of a tone (dots, bars, icons). */
export function toneColor(tone: Tone): string {
  return tone === 'neutral' ? 'var(--neutral)' : `var(--${tone})`
}
