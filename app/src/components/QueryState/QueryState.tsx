import type { ReactNode } from 'react'
import { FolderOpen, SearchX, TriangleAlert } from 'lucide-react'
import { Button, ButtonLink } from '../Button/Button'
import { EmptyState } from '../EmptyState/EmptyState'
import { Skeleton } from '../Skeleton/Skeleton'
import styles from './QueryState.module.css'

export interface QueryStateProps {
  /** Same values as `useDerivedRun().status` and the data stores. */
  status: 'idle' | 'loading' | 'ready' | 'error'
  error?: string | null
  /** Ready but nothing to show. */
  isEmpty?: boolean
  /** Overrides for each state. */
  idle?: ReactNode
  loading?: ReactNode
  empty?: ReactNode
  onRetry?: () => void
  /** Rendered only when ready and not empty; a function defers evaluation until then. */
  children: ReactNode | (() => ReactNode)
}

/** Loading / error / empty / no-run wrapper so every view handles the four states the same way. */
export function QueryState({ status, error, isEmpty, idle, loading, empty, onRetry, children }: QueryStateProps) {
  if (status === 'idle') {
    return (
      idle ?? (
        <EmptyState
          icon={<FolderOpen />}
          title="Sin ejecución activa"
          description="Carga un dataset y abre una ejecución para ver este panel."
          action={
            <ButtonLink to="/ejecuciones/nueva" variant="primary">
              Nuevo cierre
            </ButtonLink>
          }
        />
      )
    )
  }
  if (status === 'loading') {
    return (
      loading ?? (
        <div className={styles.loading} role="status">
          <span className="sr-only">Cargando…</span>
          <Skeleton width={180} height={16} />
          <Skeleton lines={4} />
        </div>
      )
    )
  }
  if (status === 'error') {
    return (
      <div role="alert">
        <EmptyState
          icon={<TriangleAlert />}
          title="No se pudo cargar"
          description={error ?? 'Error desconocido.'}
          action={onRetry && <Button onClick={onRetry}>Reintentar</Button>}
        />
      </div>
    )
  }
  if (isEmpty) {
    return empty ?? <EmptyState icon={<SearchX />} title="Sin resultados" description="No hay nada que mostrar con los filtros actuales." />
  }
  return <>{typeof children === 'function' ? children() : children}</>
}
