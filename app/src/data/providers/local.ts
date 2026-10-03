// Local provider: a phase folder or zip chosen by the user, parsed in the browser (worker),
// and run bundles imported from files. Temporary until the backend serves everything.
import type { DatasetMeta, RunBundle } from '@/domain/types'
import { bundleFromFiles, runFilesFromInput } from '../bundles/bundle'
import { pathFiles } from '../sources/fileSystemSource'
import type { SourceDescriptor } from '../sources/types'
import { openDataset, type OpenOptions } from '../worker/client'
import type { OpenedDataset, ProgressFn } from './types'

export function folderSource(input: File[] | FileSystemDirectoryHandle): SourceDescriptor {
  return Array.isArray(input) ? { kind: 'files', files: pathFiles(input) } : { kind: 'dir', handle: input }
}

export const zipSourceOf = (file: File): SourceDescriptor => ({ kind: 'zip', file, name: file.name })

interface PermissionedHandle {
  queryPermission?(d: { mode: 'read' }): Promise<PermissionState>
  requestPermission?(d: { mode: 'read' }): Promise<PermissionState>
}

/** Persisted directory handles need the user's permission again after a reload. */
async function ensureReadable(source: SourceDescriptor) {
  if (source.kind !== 'dir') return
  const h = source.handle as unknown as PermissionedHandle
  if (!h.queryPermission || (await h.queryPermission({ mode: 'read' })) === 'granted') return
  const asked = await h.requestPermission?.({ mode: 'read' }).catch(() => 'denied' as const)
  if (asked !== 'granted') throw new Error(`Sin permiso para leer la carpeta «${source.handle.name}»: actívala de nuevo con un clic`)
}

export async function openLocal(source: SourceDescriptor, options: OpenOptions, onProgress: ProgressFn): Promise<OpenedDataset> {
  await ensureReadable(source)
  return openDataset(source, options, onProgress)
}

export async function importLocalRun(input: File[] | File | FileSystemDirectoryHandle, dataset: DatasetMeta, label?: string): Promise<RunBundle> {
  const { files, name } = await runFilesFromInput(input)
  return bundleFromFiles(files, { datasetId: dataset.id, source: 'import', label, name })
}
