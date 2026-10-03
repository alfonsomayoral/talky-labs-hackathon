// Dataset worker: opens a source, builds the core and answers DatasetApi calls via comlink.
import { expose } from 'comlink'
import type { DatasetApi, JournalQuery } from '@/domain/types'
import { createSource } from '../sources'
import type { SourceDescriptor } from '../sources/types'
import { openBackend } from './backend'
import type { Progress } from './buildCore'

let backend: DatasetApi | null = null

const need = () => {
  if (!backend) throw new Error('El dataset no está abierto en el worker')
  return backend
}

const workerApi = {
  async open(desc: SourceDescriptor, options: { id?: string; name?: string; remoteId?: string }, onProgress?: (p: Progress) => void) {
    backend = await openBackend(await createSource(desc), { ...options, onProgress })
    return { meta: backend.meta, core: backend.core }
  },
  recordedTrialBalance: () => need().recordedTrialBalance(),
  queryJournal: (q: JournalQuery) => need().queryJournal(q),
  getJournalEntries: (ids: string[]) => need().getJournalEntries(ids),
  goodsReceipts: (filter?: { po?: string; vendor?: string; company?: string }) => need().goodsReceipts(filter),
  rawBankDetails: (account: string, month: string) => need().rawBankDetails(account, month),
  listFiles: (prefix?: string) => need().listFiles(prefix),
  readFile: (path: string) => need().readFile(path),
  readText: (path: string) => need().readText(path),
  einvoice: (path: string) => need().einvoice!(path),
}

export type DatasetWorkerApi = typeof workerApi

expose(workerApi)
