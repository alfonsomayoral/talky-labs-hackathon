import { useMemo } from 'react'
import type { TaskKey } from '@/domain/types'
import { useDatasetStore } from '@/data/stores'
import { useActiveRun, useDerivedRun } from '@/engine'
import { processFlow, type ProcessFlow } from './processFlow'

/** Decision map of a task for the active run (null until the run is ready). */
export function useProcessFlow(task: TaskKey | null | undefined): ProcessFlow | null {
  const { data } = useDerivedRun()
  const run = useActiveRun()
  const core = useDatasetStore((s) => s.api?.core ?? null)
  return useMemo(() => (task && data && run && core ? processFlow(task, data, core, run) : null), [task, data, run, core])
}
