// Folder picked with <input webkitdirectory>, dropped, or opened as a FileSystemDirectoryHandle.
import type { RawSource, PathFile } from './types'
import { createRootedSource } from './root'

/** Files from an <input webkitdirectory> or from filesFromDataTransfer (path in webkitRelativePath). */
export function pathFiles(files: File[]): PathFile[] {
  return files.map((file) => ({ path: file.webkitRelativePath || file.name, file }))
}

export function fileSystemSource(files: PathFile[], fallbackName = 'dataset'): RawSource {
  const byPath = new Map(files.map((f) => [f.path.replace(/\\/g, '/').replace(/^\/+/, ''), f.file]))
  const entries = [...byPath].map(([path, file]) => ({
    path,
    size: file.size,
    lastModified: 'lastModified' in file ? new Date((file as File).lastModified).toISOString() : undefined,
  }))
  return createRootedSource('folder', entries, async (p) => byPath.get(p)!, fallbackName)
}

interface IterableDirectoryHandle {
  name: string
  values(): AsyncIterable<FileSystemDirectoryHandle | FileSystemFileHandle>
}

/** Walks a directory handle; paths start with the handle's own name, like webkitRelativePath. */
export async function directoryHandleFiles(handle: FileSystemDirectoryHandle): Promise<PathFile[]> {
  const out: PathFile[] = []
  const walk = async (dir: FileSystemDirectoryHandle, prefix: string) => {
    for await (const entry of (dir as unknown as IterableDirectoryHandle).values()) {
      if (entry.name.startsWith('.') || entry.name === '__pycache__') continue
      const path = `${prefix}/${entry.name}`
      if (entry.kind === 'directory') await walk(entry as FileSystemDirectoryHandle, path)
      else out.push({ path, file: await (entry as FileSystemFileHandle).getFile() })
    }
  }
  await walk(handle, handle.name)
  return out
}

export async function directoryHandleSource(handle: FileSystemDirectoryHandle): Promise<RawSource> {
  return fileSystemSource(await directoryHandleFiles(handle), handle.name)
}
