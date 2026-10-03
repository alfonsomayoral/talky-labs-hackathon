import { apiProvider } from './api'
import { devProvider } from './dev'
import type { RemoteProvider, RemoteProviderId } from './types'

export type { DatasetOrigin, OpenedDataset, ProgressFn, RemoteProvider, RemoteProviderId } from './types'
export { folderSource, importLocalRun, openLocal, zipSourceOf } from './local'

/** Registered remote providers, in listing order. Add the backend's next transport here. */
export const remoteProviders: Record<RemoteProviderId, RemoteProvider> = { dev: devProvider, api: apiProvider }

/** Remote run ids are `<provider>:<runId>`; bare ids (e.g. from startApiRun) belong to the backend. */
export function splitRunId(id: string): { provider: RemoteProvider; runId: string } {
  const i = id.indexOf(':')
  const prefix = i > 0 ? id.slice(0, i) : ''
  if (prefix in remoteProviders) return { provider: remoteProviders[prefix as RemoteProviderId], runId: id.slice(i + 1) }
  return { provider: apiProvider, runId: id }
}
