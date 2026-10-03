// Spanish names, routes and execution order of the six tasks, and attention kind labels.
// One source for the sidebar-facing names: views and the kit read them from here.

import type { AttentionKind, TaskKey } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'

/** Execution order of the close: AP → Facturación → Bancos → Cobros → Intragrupo → Cierre. */
export const PIPELINE: readonly TaskKey[] = ['ap', 'ar_billing', 'bank_rec', 'ar_cash', 'ic', 'close']

export interface TaskInfo {
  /** Sidebar label. */
  label: string
  /** Page title of the task view. */
  title: string
  route: string
}

export const TASK_META: Record<TaskKey, TaskInfo> = {
  ap: { label: 'Bandeja AP', title: 'Bandeja de proveedores', route: '/tareas/ap' },
  ar_billing: { label: 'Facturación', title: 'Facturación AR', route: '/tareas/facturacion' },
  ar_cash: { label: 'Cobros', title: 'Aplicación de cobros', route: '/tareas/cobros' },
  bank_rec: { label: 'Bancos', title: 'Conciliación bancaria', route: '/tareas/bancos' },
  ic: { label: 'Intragrupo', title: 'Conciliación intragrupo', route: '/tareas/intragrupo' },
  close: { label: 'Cierre', title: 'Partidas de cierre', route: '/tareas/cierre' },
}

export const TASK_LABEL = Object.fromEntries(TASK_KEYS.map((t) => [t, TASK_META[t].label])) as Record<TaskKey, string>

export const KIND_LABEL: Record<AttentionKind, string> = {
  FRAUD_SIGNAL: 'Posible fraude',
  POLICY_EXCEPTION: 'Excepción de política',
  MASTER_DATA: 'Datos maestros',
  CROSS_TASK: 'Vínculo entre tareas',
  AGENT_DOUBT: 'Duda del agente',
  ESTIMATE: 'Estimación',
  MATERIAL_UNEXPLAINED: 'Diferencia sin explicar',
  DATA_QUALITY: 'Calidad de datos',
}
