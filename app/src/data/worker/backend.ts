// Everything the dataset worker answers, independent of comlink so it can run in tests
// (and in the main thread when Workers are unavailable).
import type { DatasetApi, FileEntry, GoodsReceipt, JournalEntry, JournalQuery, RawBankDetail, TrialBalanceRow } from '@/domain/types'
import { parseEInvoice } from '../parsers/einvoice'
import { parseJsonlBlob } from '../parsers/jsonl'
import type { RawSource } from '../sources/types'
import { buildCore, GOODS_RECEIPTS_PATH, type BuildOptions } from './buildCore'
import { buildJournalIndex, journalEntriesById, queryJournalIndex, type JournalIndex } from './journal'

export async function openBackend(source: RawSource, options: BuildOptions = {}): Promise<DatasetApi> {
  const built = await buildCore(source, options)
  let journal: JournalIndex | null = null
  const journalIndex = (): JournalIndex => {
    if (!journal) {
      options.onProgress?.({ phase: 'Indexando diario', done: 0, total: 1 })
      journal = buildJournalIndex(built.journal ?? new Uint8Array())
      built.journal = null
      options.onProgress?.({ phase: 'Indexando diario', done: 1, total: 1 })
    }
    return journal
  }

  let receipts: Promise<GoodsReceipt[]> | null = null
  const allReceipts = () =>
    (receipts ??= source
      .list()
      .then((files) => (files.some((f) => f.path === GOODS_RECEIPTS_PATH) ? source.read(GOODS_RECEIPTS_PATH).then((b) => parseJsonlBlob<GoodsReceipt>(b)) : [])))

  return {
    meta: built.meta,
    core: built.core,
    recordedTrialBalance: async (): Promise<TrialBalanceRow[]> => journalIndex().trialBalance,
    queryJournal: async (q: JournalQuery) => queryJournalIndex(journalIndex(), q),
    getJournalEntries: async (ids: string[]): Promise<JournalEntry[]> => journalEntriesById(journalIndex(), ids),
    goodsReceipts: async (filter = {}) =>
      (await allReceipts()).filter(
        (g) => (!filter.po || g.po === filter.po) && (!filter.vendor || g.vendor === filter.vendor) && (!filter.company || g.company === filter.company),
      ),
    rawBankDetails: async (account: string, month: string): Promise<RawBankDetail[]> => built.rawBank.get(`${account}/${month}`) ?? [],
    listFiles: async (prefix?: string): Promise<FileEntry[]> => (await source.list()).filter((f) => !prefix || f.path.startsWith(prefix)),
    readFile: (path) => source.read(path),
    readText: (path) => source.text(path),
    einvoice: async (path) => (path.toLowerCase().endsWith('.xml') ? parseEInvoice(await source.text(path)) : null),
  }
}
