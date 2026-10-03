// Labels of the sidebar context switcher.
import type { Company } from '@/domain/types'

/** «Kalmora Infraestructuras y Servicios, S.A.» (the holding) → «Grupo Kalmora»; null without a holding. */
export function groupName(companies: readonly Company[] | null | undefined): string | null {
  const holding = companies?.find((c) => c.role === 'holding')
  const first = holding?.name.trim().split(/\s+/)[0]?.replace(/[^\p{L}\p{N}]+$/u, '')
  return first ? `Grupo ${first}` : null
}

const MONTH = new Intl.DateTimeFormat('es-ES', { month: 'long', timeZone: 'UTC' })

/** `2026-07` → `Julio 2026`. */
export function monthLabel(month: string): string {
  const [year, m] = month.split('-').map(Number)
  if (!year || !m) return '—'
  const name = MONTH.format(new Date(Date.UTC(year, m - 1, 1)))
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} ${year}`
}
