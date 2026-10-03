// Labels, routes and execution order of the six tasks, and how each run source is shown.
import type { RunBundle, RunSource, TaskKey } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'

/** Execution order of the close: AP → Facturación → Bancos → Cobros → Intragrupo → Cierre. */
export const PIPELINE: readonly TaskKey[] = ['ap', 'ar_billing', 'bank_rec', 'ar_cash', 'ic', 'close']

export const TASK_META: Record<TaskKey, { label: string; route: string }> = {
  ap: { label: 'Bandeja AP', route: '/tareas/ap' },
  ar_billing: { label: 'Facturación', route: '/tareas/facturacion' },
  bank_rec: { label: 'Bancos', route: '/tareas/bancos' },
  ar_cash: { label: 'Cobros', route: '/tareas/cobros' },
  ic: { label: 'Intragrupo', route: '/tareas/intragrupo' },
  close: { label: 'Cierre', route: '/tareas/cierre' },
}

export const RUN_SOURCE: Record<RunSource, { label: string; description: string }> = {
  golden: { label: 'Referencia', description: 'Solución de referencia (golden/)' },
  import: { label: 'Importada', description: 'Resultados importados (JSONL, carpeta o zip)' },
  api: { label: 'Backend', description: 'Cierre ejecutado por el backend' },
}

export const filesPresent = (run: RunBundle): number => TASK_KEYS.filter((t) => run.present[t]).length

export const rowsDelivered = (run: RunBundle): number => TASK_KEYS.reduce((n, t) => n + (run.present[t] ? run.deliverables[t].length : 0), 0)

/** Route of the run page (ids contain dots and colons). */
export const runPath = (runId: string) => `/ejecuciones/${encodeURIComponent(runId)}`
