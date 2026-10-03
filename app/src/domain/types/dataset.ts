// A loaded phase folder (inputs). Small/medium files are loaded eagerly into `core`;
// the journal (36–40 MB) and raw documents are loaded on demand through `DatasetApi`.

import type {
  ApDocumentLogEntry,
  ApInvoice,
  ArInvoice,
  BankAccount,
  BillingHistoryEntry,
  ChartAccount,
  Company,
  ContractorCertificate,
  CostCenter,
  Customer,
  FactoringAssignment,
  FxRate,
  GoodsReceipt,
  IntercompanyAgreements,
  JournalEntry,
  OpenItem,
  PenaltyNotice,
  Project,
  PromissoryNote,
  PurchaseOrder,
  SalesContract,
  SepaRemittance,
  TaxCodes,
  Vendor,
} from './erp'
import type { ApInboxDoc, ArInbox, DatasetPath, FileEntry } from './inbox'
import type { BankStatement, RawBankDetail } from './bank'
import type { Tasks } from './tasks'
import type { Golden, TrialBalanceRow } from './golden'

export type DatasetSourceKind = 'folder' | 'zip' | 'http'

export interface DatasetInventory {
  companies: number
  apDocuments: number
  apByChannel: Record<string, number>
  arBillingItems: number
  arRemittanceFiles: number
  arNotices: number
  bankAccounts: number
  statementsByFormat: Record<string, number>
  journalMonths: string[]
  journalBytes: number
  hasGolden: boolean
  files: number
  bytes: number
  warnings: string[]
}

export interface DatasetMeta {
  id: string
  name: string
  /** Month being closed, `YYYY-MM` (from tasks/close.json). */
  month: string
  sourceKind: DatasetSourceKind
  loadedAt: string
  inventory: DatasetInventory
}

export interface DatasetCore {
  companies: Company[]
  chartOfAccounts: ChartAccount[]
  taxCodes: TaxCodes
  costCenters: CostCenter[]
  projects: Project[]
  vendors: Vendor[]
  contractorCertificates: ContractorCertificate[]
  customers: Customer[]
  salesContracts: SalesContract[]
  purchaseOrders: PurchaseOrder[]
  openItems: OpenItem[]
  apInvoices: ApInvoice[]
  apDocumentLog: ApDocumentLogEntry[]
  arInvoices: ArInvoice[]
  billingHistory: BillingHistoryEntry[]
  promissoryNotes: PromissoryNote[]
  factoringAssignments: FactoringAssignment[]
  sepaRemittances: SepaRemittance[]
  penaltyNotices: PenaltyNotice[]
  intercompanyAgreements: IntercompanyAgreements
  fxRates: FxRate[]
  bankAccounts: BankAccount[]
  tasks: Tasks
  apInbox: ApInboxDoc[]
  arInbox: ArInbox
  /** All statements (4 months × 12 accounts) with their lines. */
  bankStatements: BankStatement[]
  golden: Golden | null
}

export interface JournalQuery {
  company?: string
  account?: string
  accountPrefix?: string
  source?: string
  from?: string
  to?: string
  text?: string
  ids?: string[]
  offset?: number
  limit?: number
}

export interface DatasetApi {
  meta: DatasetMeta
  core: DatasetCore
  /** Recorded trial balance computed from the full journal (balance = Σdebit − Σcredit). */
  recordedTrialBalance(): Promise<TrialBalanceRow[]>
  /** Journal entries matching a query (runs in the worker; never returns the whole journal by default). */
  queryJournal(q: JournalQuery): Promise<{ total: number; entries: JournalEntry[] }>
  /** Entries by id (e.g. to resolve `<id>#<line>` book lines). */
  getJournalEntries(ids: string[]): Promise<JournalEntry[]>
  goodsReceipts(filter?: { po?: string; vendor?: string; company?: string }): Promise<GoodsReceipt[]>
  /** Raw details of statement lines from the original N43 / CAMT.053 / CSV. */
  rawBankDetails(account: string, month: string): Promise<RawBankDetail[]>
  listFiles(prefix?: string): Promise<FileEntry[]>
  readFile(path: DatasetPath): Promise<Blob>
  readText(path: DatasetPath): Promise<string>
}
