// Route registry. Each page is lazy-loaded from the folder that owns it (app/PLAN.md §3.2).
// Owned by the coordinator after phase 1 — feature agents only edit their own folder.
import type { RouteObject } from 'react-router'
import AppShell from '@/shell/AppShell'

const page = (load: () => Promise<{ default: React.ComponentType }>) => async () => ({ Component: (await load()).default })

export const routes: RouteObject[] = [
  {
    path: '/',
    Component: AppShell,
    children: [
      { index: true, lazy: page(() => import('@/features/overview/OverviewPage')) },
      { path: 'atencion', lazy: page(() => import('@/features/attention/AttentionPage')) },
      { path: 'actividad', lazy: page(() => import('@/features/activity/ActivityPage')) },
      { path: 'asistente', lazy: page(() => import('@/features/assistant/AssistantPage')) },
      { path: 'tareas/ap', lazy: page(() => import('@/features/tasks/ap/ApPage')) },
      { path: 'tareas/facturacion', lazy: page(() => import('@/features/tasks/ar-billing/ArBillingPage')) },
      { path: 'tareas/cobros', lazy: page(() => import('@/features/tasks/ar-cash/ArCashPage')) },
      { path: 'tareas/bancos', lazy: page(() => import('@/features/tasks/bank/BankPage')) },
      { path: 'tareas/bancos/:account', lazy: page(() => import('@/features/tasks/bank/BankAccountPage')) },
      { path: 'tareas/intragrupo', lazy: page(() => import('@/features/tasks/ic/IcPage')) },
      { path: 'tareas/cierre', lazy: page(() => import('@/features/tasks/close/ClosePage')) },
      { path: 'balance', lazy: page(() => import('@/features/ledger/LedgerPage')) },
      { path: 'datos/*', lazy: page(() => import('@/features/data-explorer/DataExplorerPage')) },
      { path: 'entregables', lazy: page(() => import('@/features/deliverables/DeliverablesPage')) },
      { path: 'ejecuciones', lazy: page(() => import('@/features/runs/RunsPage')) },
      { path: 'ejecuciones/nueva', lazy: page(() => import('@/features/runs/NewRunPage')) },
      { path: 'ejecuciones/:runId', lazy: page(() => import('@/features/runs/RunLivePage')) },
      { path: 'comparar', lazy: page(() => import('@/features/compare/ComparePage')) },
      { path: 'coste', lazy: page(() => import('@/features/observability/CostPage')) },
      { path: 'dev/ui', lazy: page(() => import('@/components/gallery/GalleryPage')) },
      { path: 'dev/data', lazy: page(() => import('@/data/devtools/DataDebugPage')) },
      { path: '*', lazy: page(() => import('@/shell/NotFoundPage')) },
    ],
  },
]
