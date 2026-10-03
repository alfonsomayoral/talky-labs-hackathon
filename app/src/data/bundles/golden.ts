// The reference solution (golden/) opened as a run, without generator-only fields.
import { GOLDEN_INTERNAL_FIELDS, TASK_KEYS, type DatasetMeta, type Deliverables, type Golden, type RunBundle, type TaskKey } from '@/domain/types'

export function stripGolden(golden: Golden): Deliverables {
  const out = {} as Record<TaskKey, unknown[]>
  for (const task of TASK_KEYS) {
    const drop = GOLDEN_INTERNAL_FIELDS[task]
    out[task] = (golden.deliverables[task] as object[]).map((row) =>
      drop.length ? Object.fromEntries(Object.entries(row).filter(([k]) => !drop.includes(k))) : { ...row },
    )
  }
  return out as unknown as Deliverables
}

export const goldenRunId = (datasetId: string) => `${datasetId}.golden`

export function goldenRun(meta: DatasetMeta, golden: Golden): RunBundle {
  return {
    id: goldenRunId(meta.id),
    datasetId: meta.id,
    source: 'golden',
    label: 'Referencia (golden)',
    createdAt: new Date().toISOString(),
    manifest: null,
    deliverables: stripGolden(golden),
    present: Object.fromEntries(TASK_KEYS.map((t) => [t, true])) as Record<TaskKey, boolean>,
    events: null,
    attention: null,
  }
}
