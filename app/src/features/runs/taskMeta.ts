// How each run source is shown, and counts of a run bundle.
import type { RunBundle, RunSource } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'

export const RUN_SOURCE: Record<RunSource, { label: string; description: string }> = {
  golden: { label: 'Referencia', description: 'Solución de referencia (golden/)' },
  import: { label: 'Importada', description: 'Resultados importados (JSONL, carpeta o zip)' },
  api: { label: 'Backend', description: 'Cierre ejecutado por el backend' },
}

export const filesPresent = (run: RunBundle): number => TASK_KEYS.filter((t) => run.present[t]).length

export const rowsDelivered = (run: RunBundle): number => TASK_KEYS.reduce((n, t) => n + (run.present[t] ? run.deliverables[t].length : 0), 0)

/** Route of the run page (ids contain dots and colons). */
export const runPath = (runId: string) => `/ejecuciones/${encodeURIComponent(runId)}`
