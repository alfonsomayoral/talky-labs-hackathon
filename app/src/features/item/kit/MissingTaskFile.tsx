import { FileX } from 'lucide-react'
import type { TaskKey } from '@/domain/types'
import { DELIVERABLE_FILES } from '@/domain/types'
import { ButtonLink, EmptyState, Mono, PageHeader } from '@/components'
import { TASK_META } from './labels'

/** Task view when the active run does not deliver that task's file (it scores 0 in that task). */
export function MissingTaskFile({ task }: { task: TaskKey }) {
  return (
    <>
      <PageHeader title={TASK_META[task].title} />
      <EmptyState
        icon={<FileX />}
        title={
          <>
            La ejecución no trae <Mono>{DELIVERABLE_FILES[task]}</Mono>
          </>
        }
        description="Sin ese fichero no hay partidas que revisar en esta tarea, y su nota es 0. Importa la entrega completa o revisa qué falta en Entregables."
        action={
          <ButtonLink to="/entregables" size="sm">
            Ver Entregables
          </ButtonLink>
        }
      />
    </>
  )
}
