export type { RawSource, PathFile, SourceDescriptor } from './types'
export { fileSystemSource, pathFiles, directoryHandleFiles, directoryHandleSource } from './fileSystemSource'
export { zipSource } from './zipSource'
export { httpSource } from './httpSource'
export { filesFromDataTransfer } from './dataTransfer'
export { detectPhaseRoots } from './root'
import type { RawSource, SourceDescriptor } from './types'
import { directoryHandleSource, fileSystemSource } from './fileSystemSource'
import { httpSource } from './httpSource'
import { zipSource } from './zipSource'

export function createSource(d: SourceDescriptor): Promise<RawSource> {
  switch (d.kind) {
    case 'files':
      return Promise.resolve(fileSystemSource(d.files, d.name))
    case 'dir':
      return directoryHandleSource(d.handle)
    case 'zip':
      return zipSource(d.file, d.name)
    case 'http':
      return httpSource(d.baseUrl, d.name)
  }
}
