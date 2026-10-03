// Main-thread side: spawns the dataset worker and exposes it as a DatasetApi whose `core`
// is materialized once. Falls back to running in-thread where Workers do not exist (tests).
import { proxy, releaseProxy, wrap } from 'comlink'
import type { DatasetApi } from '@/domain/types'
import type { SourceDescriptor } from '../sources/types'
import type { Progress } from './buildCore'
import type { DatasetWorkerApi } from './dataset.worker'

export interface OpenedDataset {
  api: DatasetApi
  close(): void
}

export interface OpenOptions {
  id?: string
  name?: string
  remoteId?: string
}

function memoTrialBalance(api: DatasetApi): DatasetApi {
  let tb: ReturnType<DatasetApi['recordedTrialBalance']> | null = null
  const original = api.recordedTrialBalance
  return {
    ...api,
    recordedTrialBalance: () => {
      tb ??= original().catch((e: unknown) => {
        tb = null
        throw e
      })
      return tb
    },
  }
}

export async function openDataset(desc: SourceDescriptor, options: OpenOptions, onProgress: (p: Progress) => void): Promise<OpenedDataset> {
  if (typeof Worker === 'undefined') {
    const [{ openBackend }, { createSource }] = await Promise.all([import('./backend'), import('../sources')])
    const backend = await openBackend(await createSource(desc), { ...options, onProgress })
    return { api: memoTrialBalance(backend), close: () => {} }
  }

  const worker = new Worker(new URL('./dataset.worker.ts', import.meta.url), { type: 'module', name: 'kalmora-dataset' })
  const remote = wrap<DatasetWorkerApi>(worker)
  const close = () => {
    remote[releaseProxy]()
    worker.terminate()
  }
  const crashed = new Promise<never>((_, reject) =>
    worker.addEventListener('error', (e) => reject(new Error(e.message || 'No se pudo iniciar el worker de datos'))),
  )
  try {
    const { meta, core } = await Promise.race([remote.open(desc, options, proxy(onProgress)), crashed])
    const api: DatasetApi = {
      meta,
      core,
      recordedTrialBalance: () => remote.recordedTrialBalance(),
      queryJournal: (q) => remote.queryJournal(q),
      getJournalEntries: (ids) => remote.getJournalEntries(ids),
      goodsReceipts: (filter) => remote.goodsReceipts(filter),
      rawBankDetails: (account, month) => remote.rawBankDetails(account, month),
      listFiles: (prefix) => remote.listFiles(prefix),
      readFile: (path) => remote.readFile(path),
      readText: (path) => remote.readText(path),
      einvoice: (path) => remote.einvoice(path),
    }
    return { api: memoTrialBalance(api), close }
  } catch (e) {
    close()
    throw e
  }
}
