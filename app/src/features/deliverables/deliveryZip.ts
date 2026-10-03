// The delivery package: `entrega_<runId>/` with the six JSONL as they are in the run
// (one JSON.stringify(row) per line, absent files omitted), manifest.json and overrides.jsonl.
import { strToU8, zipSync } from 'fflate'
import type { DatasetMeta, RunBundle, RunManifest, TaskKey } from '@/domain/types'
import { DELIVERABLE_FILES, TASK_KEYS } from '@/domain/types'

export const toJsonl = (rows: readonly unknown[]): string => rows.map((r) => `${JSON.stringify(r)}\n`).join('')

export const deliveryFolder = (runId: string) => `entrega_${runId.replace(/[^A-Za-z0-9_.-]+/g, '-')}`

export interface ManifestContext {
  dataset: Pick<DatasetMeta, 'id' | 'name' | 'month'> | null
  /** Human overrides recorded for this run (overrides store). */
  overrides: number
  now?: string
}

/** The run's own manifest, completed with what the delivery contains. */
export function deliveryManifest(run: RunBundle, ctx: ManifestContext): RunManifest {
  const present = TASK_KEYS.filter((t) => run.present[t])
  return {
    run_id: run.id,
    dataset: ctx.dataset?.name ?? run.datasetId,
    ...(ctx.dataset?.month ? { month: ctx.dataset.month } : {}),
    source: run.source,
    created_at: run.createdAt,
    exported_at: ctx.now ?? new Date().toISOString(),
    files: present.map((t) => DELIVERABLE_FILES[t]),
    counts: Object.fromEntries(present.map((t) => [t, run.deliverables[t].length])) as Partial<Record<TaskKey, number>>,
    ...run.manifest,
    human_overrides: ctx.overrides,
  }
}

export interface DeliveryExtras {
  manifest: RunManifest
  /** Contents of overrides.jsonl; the file is left out when empty. */
  overridesJsonl?: string
}

export function buildDeliveryZip(run: RunBundle, extras: DeliveryExtras): Uint8Array {
  const root = deliveryFolder(run.id)
  const files: Record<string, Uint8Array> = {}
  for (const t of TASK_KEYS) if (run.present[t]) files[`${root}/${DELIVERABLE_FILES[t]}`] = strToU8(toJsonl(run.deliverables[t]))
  files[`${root}/manifest.json`] = strToU8(`${JSON.stringify(extras.manifest, null, 2)}\n`)
  const overrides = extras.overridesJsonl?.trim()
  if (overrides) files[`${root}/overrides.jsonl`] = strToU8(`${overrides}\n`)
  return zipSync(files, { level: 6 })
}
