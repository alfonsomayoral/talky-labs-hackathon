import type { DatasetPath, DatasetSourceKind, FileEntry } from '@/domain/types'

/** Read access to the files of one phase folder. Paths are relative to the phase root. */
export interface RawSource {
  kind: DatasetSourceKind
  /** Name of the phase root folder (e.g. `phase_dev`). */
  name: string
  /** Notes found while opening (e.g. other phase folders ignored in the selection). */
  notes: string[]
  list(): Promise<FileEntry[]>
  read(path: DatasetPath): Promise<Blob>
  text(path: DatasetPath): Promise<string>
}

/** A file plus its path relative to the selection (webkitRelativePath or the drop path). */
export interface PathFile {
  path: string
  file: Blob
}

/** Serializable description of where a dataset comes from (sent to the worker, persisted in IndexedDB). */
export type SourceDescriptor =
  | { kind: 'files'; files: PathFile[]; name?: string }
  | { kind: 'dir'; handle: FileSystemDirectoryHandle }
  | { kind: 'zip'; file: Blob; name: string }
  | { kind: 'http'; baseUrl: string; name: string }
