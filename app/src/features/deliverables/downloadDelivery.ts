// Delivery zip of a run as a browser download, shared by Entregables and the ⌘K action.
import type { RunBundle } from '@/domain/types'
import { useDatasetStore } from '@/data/stores'
import { useOverridesStore } from '../attention/overridesStore'
import { buildDeliveryZip, deliveryFolder, deliveryManifest } from './deliveryZip'
import { saveFile } from './download'

/** Builds the zip (6 JSONL + manifest.json + overrides.jsonl) and saves it; returns the file name. */
export function downloadDelivery(run: RunBundle): string {
  const overrides = useOverridesStore.getState()
  const manifest = deliveryManifest(run, { dataset: useDatasetStore.getState().api?.meta ?? null, overrides: overrides.byRun[run.id]?.length ?? 0 })
  const zip = buildDeliveryZip(run, { manifest, overridesJsonl: overrides.toJsonl(run.id) })
  const name = `${deliveryFolder(run.id)}.zip`
  saveFile(name, zip as Uint8Array<ArrayBuffer>, 'application/zip')
  return name
}
