// Pure builder: reads a phase folder through a RawSource and returns its metadata and the
// eagerly-loaded core. The journal is only read as bytes here (months scan); it is parsed
// lazily by the journal index. Goods receipts are not read at all (lazy in the worker).
import {
  DELIVERABLE_FILES,
  TASK_KEYS,
  type ApInboxDoc,
  type ArBillingInboxItem,
  type BankLine,
  type BankStatement,
  type BillingItemMeta,
  type DatasetCore,
  type DatasetMeta,
  type Deliverables,
  type FileEntry,
  type Golden,
  type GoldenSummary,
  type InboxMessage,
  type RawBankDetail,
  type Tasks,
  type TrialBalanceRow,
} from '@/domain/types'
import { mapToLines, parseRawStatement, statementFormat } from '../parsers/bankStatement'
import { parseJsonlBlob, parseJsonlText } from '../parsers/jsonl'
import type { RawSource } from '../sources/types'

export interface Progress {
  phase: string
  done: number
  total: number
}

export interface BuildOptions {
  /** Dataset id; defaults to `<root folder>-<month>`. */
  id?: string
  name?: string
  /** Id on the dev middleware or backend, kept in the metadata. */
  remoteId?: string
  onProgress?: (p: Progress) => void
}

export interface BuildResult {
  meta: DatasetMeta
  core: DatasetCore
  /** Raw statement details by `<account>/<month>`, parsed while verifying the statements. */
  rawBank: Map<string, RawBankDetail[]>
  /** Bytes of erp/journal_entries.jsonl for the lazy journal index (null when absent). */
  journal: Uint8Array | null
}

const ERP_JSONL = {
  chartOfAccounts: 'chart_of_accounts.jsonl',
  costCenters: 'cost_centers.jsonl',
  projects: 'projects.jsonl',
  vendors: 'vendors.jsonl',
  contractorCertificates: 'contractor_certificates.jsonl',
  customers: 'customers.jsonl',
  salesContracts: 'sales_contracts.jsonl',
  purchaseOrders: 'purchase_orders.jsonl',
  openItems: 'open_items.jsonl',
  apInvoices: 'ap_invoices.jsonl',
  apDocumentLog: 'ap_document_log.jsonl',
  arInvoices: 'ar_invoices.jsonl',
  billingHistory: 'billing_history.jsonl',
  promissoryNotes: 'promissory_notes.jsonl',
  factoringAssignments: 'factoring_assignments.jsonl',
  sepaRemittances: 'sepa_remittances.jsonl',
  penaltyNotices: 'penalty_notices.jsonl',
  fxRates: 'fx_rates.jsonl',
  bankAccounts: 'bank_accounts.jsonl',
} as const satisfies Partial<Record<keyof DatasetCore, string>>

export const JOURNAL_PATH = 'erp/journal_entries.jsonl'
export const GOODS_RECEIPTS_PATH = 'erp/goods_receipts.jsonl'

export function datasetId(name: string, month: string): string {
  const slug = name.toLowerCase().replace(/[^a-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'dataset'
  return `${slug}-${month}`
}

async function mapLimit<T, R>(items: T[], limit: number, fn: (item: T, i: number) => Promise<R>, onDone?: (n: number) => void): Promise<R[]> {
  const out: R[] = Array.from({ length: items.length })
  let next = 0
  let done = 0
  const worker = async () => {
    while (next < items.length) {
      const i = next++
      out[i] = await fn(items[i], i)
      onDone?.(++done)
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, worker))
  return out
}

const preview = (xs: string[]) => xs.slice(0, 5).join(', ') + (xs.length > 5 ? `… (+${xs.length - 5})` : '')

/** Months (`YYYY-MM`) of `posting_date` and the entry count, without parsing the JSON. */
export function scanJournal(bytes: Uint8Array): { months: string[]; entries: number } {
  const text = new TextDecoder().decode(bytes)
  const months = new Set<string>()
  for (const m of text.matchAll(/"posting_date"\s*:\s*"(\d{4}-\d{2})/g)) months.add(m[1])
  let entries = 0
  for (const line of text.split('\n')) if (line.trim()) entries++
  return { months: [...months].sort(), entries }
}

export async function buildCore(source: RawSource, options: BuildOptions = {}): Promise<BuildResult> {
  const progress = (phase: string, done: number, total: number) => options.onProgress?.({ phase, done, total })
  const warnings: string[] = [...source.notes]
  const warn = (w: string) => warnings.push(w)

  progress('Listando ficheros', 0, 1)
  const files = await source.list()
  const byPath = new Map<string, FileEntry>(files.map((f) => [f.path, f]))
  const has = (p: string) => byPath.has(p)
  const under = (prefix: string) => files.filter((f) => f.path.startsWith(prefix))

  const readJson = async <T>(path: string, fallback: T): Promise<T> => {
    if (!has(path)) {
      warn(`Falta ${path}`)
      return fallback
    }
    try {
      return JSON.parse(await source.text(path)) as T
    } catch (e) {
      throw new Error(`${path}: ${e instanceof Error ? e.message : String(e)}`)
    }
  }
  const readJsonl = async <T>(path: string, required = true): Promise<T[]> => {
    if (!has(path)) {
      if (required) warn(`Falta ${path}`)
      return []
    }
    try {
      return await parseJsonlBlob<T>(await source.read(path))
    } catch (e) {
      throw new Error(`${path}: ${e instanceof Error ? e.message : String(e)}`)
    }
  }

  // ---------------------------------------------------------------- tasks
  if (!has('tasks/close.json')) throw new Error('Falta tasks/close.json: no se puede saber qué mes se cierra')
  progress('Leyendo tareas', 0, 6)
  const tasks: Tasks = {
    ap_documents: await readJson<string[]>('tasks/ap_documents.json', []),
    ar_billing_items: await readJson<string[]>('tasks/ar_billing_items.json', []),
    ar_receipts: await readJson<string[]>('tasks/ar_receipts.json', []),
    bank_accounts: await readJson<string[]>('tasks/bank_accounts.json', []),
    intercompany: await readJson('tasks/intercompany.json', { pairs: [], accounts: [] }),
    close: await readJson('tasks/close.json', { month: '', steps: [] }),
  }
  progress('Leyendo tareas', 6, 6)
  const month = tasks.close.month
  if (!/^\d{4}-\d{2}$/.test(month)) throw new Error(`tasks/close.json: mes no válido «${month}»`)
  const name = options.name ?? source.name

  // ---------------------------------------------------------------- erp masters
  const erpKeys = Object.keys(ERP_JSONL) as (keyof typeof ERP_JSONL)[]
  const erpTotal = erpKeys.length + 3
  let erpDone = 0
  progress('Leyendo maestros', 0, erpTotal)
  const tick = () => progress('Leyendo maestros', ++erpDone, erpTotal)
  const erp = Object.fromEntries(
    await mapLimit(erpKeys, 6, async (k) => {
      const rows = await readJsonl(`erp/${ERP_JSONL[k]}`)
      tick()
      return [k, rows] as const
    }),
  ) as { [K in keyof typeof ERP_JSONL]: DatasetCore[K] }
  const companies = await readJson<DatasetCore['companies']>('erp/companies.json', [])
  tick()
  const taxCodes = await readJson<DatasetCore['taxCodes']>('erp/tax_codes.json', { tax_codes: {}, withholdings: {}, customer_deductions: {} })
  tick()
  const intercompanyAgreements = await readJson<DatasetCore['intercompanyAgreements']>('erp/intercompany_agreements.json', {
    management_fees: {},
    loan: { id: '', principal: 0, rate_bp: 0, basis: '', start: '', lender: '', borrower: '', note: '' },
    cash_pooling: { header: '', participants: [], scheme: '', interest: '' },
    ute: {},
  })
  tick()

  // ---------------------------------------------------------------- inbox
  const dirsUnder = (prefix: string) => {
    const dirs = new Map<string, string[]>()
    for (const f of under(prefix)) {
      const rest = f.path.slice(prefix.length)
      const slash = rest.indexOf('/')
      if (slash <= 0) continue
      const dir = rest.slice(0, slash)
      dirs.set(dir, [...(dirs.get(dir) ?? []), f.path])
    }
    return [...dirs].sort(([a], [b]) => a.localeCompare(b))
  }
  const apDirs = dirsUnder('inbox/ap/')
  const billingDirs = dirsUnder('inbox/ar/billing/')
  const inboxTotal = apDirs.length + billingDirs.length
  let inboxDone = 0
  const inboxTick = () => {
    inboxDone++
    if (inboxDone % 10 === 0 || inboxDone === inboxTotal) progress('Leyendo bandeja', inboxDone, inboxTotal)
  }
  progress('Leyendo bandeja', 0, inboxTotal)

  const apInbox: ApInboxDoc[] = await mapLimit(apDirs, 16, async ([docId, paths]) => {
    const messagePath = `inbox/ap/${docId}/message.json`
    const docFiles = paths.filter((p) => p !== messagePath)
    let message: InboxMessage
    if (paths.includes(messagePath)) message = JSON.parse(await source.text(messagePath)) as InboxMessage
    else {
      warn(`Falta ${messagePath}`)
      message = { doc_id: docId, channel: 'unknown', received_at: '', mailbox: '', attachments: docFiles.map((p) => p.split('/').pop()!) }
    }
    inboxTick()
    return { docId, message, files: docFiles }
  })

  const billing: ArBillingInboxItem[] = await mapLimit(billingDirs, 16, async ([item, paths]) => {
    const metaPath = paths.find((p) => p.endsWith('/item.json')) ?? paths.find((p) => p.endsWith('.json'))
    const meta = metaPath ? (JSON.parse(await source.text(metaPath)) as BillingItemMeta) : null
    if (!meta) warn(`inbox/ar/billing/${item}: sin fichero de metadatos (item.json)`)
    inboxTick()
    return { item, meta, files: paths.filter((p) => p !== metaPath) }
  })
  const arInbox = {
    billing,
    remittances: under('inbox/ar/remittances/').map((f) => f.path),
    notices: under('inbox/ar/notices/').map((f) => f.path),
  }

  // ---------------------------------------------------------------- bank statements
  const lineFiles = files.filter((f) => /^bank\/[^/]+\/\d{4}-\d{2}\.lines\.jsonl$/.test(f.path))
  const rawBank = new Map<string, RawBankDetail[]>()
  const statementsByFormat: Record<string, number> = {}
  progress('Leyendo extractos', 0, lineFiles.length)
  const bankStatements: BankStatement[] = await mapLimit(
    lineFiles,
    8,
    async (f): Promise<BankStatement> => {
      const [, account, file] = f.path.split('/')
      const stmMonth = file.slice(0, 7)
      const prefix = `bank/${account}/${stmMonth}.`
      const rawPath = files.map((x) => x.path).find((p) => p.startsWith(prefix) && !p.endsWith('.lines.jsonl') && statementFormat(p)) ?? null
      const lines = parseJsonlText<BankLine>(await source.text(f.path))
      const label = `${account} ${stmMonth}`
      if (!rawPath) {
        warn(`${label}: no hay extracto original (N43, CAMT.053 o CSV)`)
        return { account, month: stmMonth, format: 'n43', lines, rawPath: null }
      }
      const format = statementFormat(rawPath)!
      statementsByFormat[format] = (statementsByFormat[format] ?? 0) + 1
      // Raw parsing only enriches evidence (details, balances): a failure is a warning, never fatal.
      let mapped: ReturnType<typeof mapToLines>
      try {
        mapped = mapToLines(parseRawStatement(format, await source.text(rawPath)), lines, label)
      } catch (e) {
        warn(`${label}: no se pudo leer ${rawPath} (${e instanceof Error ? e.message : String(e)})`)
        return { account, month: stmMonth, format, lines, rawPath }
      }
      mapped.warnings.forEach(warn)
      rawBank.set(`${account}/${stmMonth}`, mapped.details)
      return {
        account,
        month: stmMonth,
        format,
        lines,
        rawPath,
        ...(mapped.opening !== null && { opening: mapped.opening }),
        ...(mapped.closing !== null && { closing: mapped.closing }),
      }
    },
    (n) => progress('Leyendo extractos', n, lineFiles.length),
  )
  bankStatements.sort((a, b) => a.account.localeCompare(b.account) || a.month.localeCompare(b.month))

  // ---------------------------------------------------------------- golden
  let golden: Golden | null = null
  if (under('golden/').length) {
    progress('Leyendo golden', 0, 1)
    const deliverables: Record<string, unknown[]> = {}
    for (const k of TASK_KEYS) deliverables[k] = await readJsonl(`golden/${DELIVERABLE_FILES[k]}`)
    golden = {
      deliverables: deliverables as unknown as Deliverables,
      trialBalanceTruth: await readJsonl<TrialBalanceRow>('golden/trial_balance_truth.jsonl'),
      trialBalanceRecorded: await readJsonl<TrialBalanceRow>('golden/trial_balance_recorded.jsonl'),
      summary: has('golden/summary.json') ? JSON.parse(await source.text('golden/summary.json')) as GoldenSummary : null,
    }
    progress('Leyendo golden', 1, 1)
  }

  // ---------------------------------------------------------------- journal (bytes only)
  let journal: Uint8Array | null = null
  let journalMonths: string[] = []
  if (has(JOURNAL_PATH)) {
    progress('Leyendo diario', 0, 1)
    journal = new Uint8Array(await (await source.read(JOURNAL_PATH)).arrayBuffer())
    journalMonths = scanJournal(journal).months
    progress('Leyendo diario', 1, 1)
  } else warn(`Falta ${JOURNAL_PATH}`)
  if (!has(GOODS_RECEIPTS_PATH)) warn(`Falta ${GOODS_RECEIPTS_PATH}`)

  // ---------------------------------------------------------------- cross checks
  const apIds = new Set(apInbox.map((d) => d.docId))
  const missingAp = tasks.ap_documents.filter((id) => !apIds.has(id))
  if (missingAp.length) warn(`${missingAp.length} documentos de tasks/ap_documents.json no están en inbox/ap/: ${preview(missingAp)}`)
  const billingIds = new Set(billing.map((b) => b.item))
  const missingBilling = tasks.ar_billing_items.filter((id) => !billingIds.has(id))
  if (missingBilling.length) warn(`${missingBilling.length} partidas de tasks/ar_billing_items.json no están en inbox/ar/billing/: ${preview(missingBilling)}`)
  const monthStatements = bankStatements.filter((s) => s.month === month)
  const accountsWithMonth = new Set(monthStatements.map((s) => s.account))
  const missingBank = tasks.bank_accounts.filter((a) => !accountsWithMonth.has(a))
  if (missingBank.length) warn(`Sin extracto de ${month} para: ${preview(missingBank)}`)
  const monthLines = new Set(monthStatements.flatMap((s) => s.lines.map((l) => l.bank_line)))
  const missingReceipts = tasks.ar_receipts.filter((id) => !monthLines.has(id))
  if (missingReceipts.length) warn(`${missingReceipts.length} cobros de tasks/ar_receipts.json no aparecen en los extractos de ${month}: ${preview(missingReceipts)}`)
  const masterAccounts = new Set(erp.bankAccounts.map((a) => a.id))
  const unknownAccounts = tasks.bank_accounts.filter((a) => !masterAccounts.has(a))
  if (unknownAccounts.length) warn(`Cuentas de tasks/bank_accounts.json sin ficha en erp/bank_accounts.jsonl: ${preview(unknownAccounts)}`)
  if (golden?.summary && golden.summary.month !== month) warn(`golden/summary.json es de ${golden.summary.month} y tasks/close.json de ${month}`)

  const apByChannel: Record<string, number> = {}
  for (const d of apInbox) apByChannel[d.message.channel] = (apByChannel[d.message.channel] ?? 0) + 1

  const core: DatasetCore = {
    companies,
    taxCodes,
    intercompanyAgreements,
    ...erp,
    tasks,
    apInbox,
    arInbox,
    bankStatements,
    golden,
  }
  const meta: DatasetMeta = {
    id: options.id ?? datasetId(name, month),
    name,
    month,
    sourceKind: source.kind,
    ...(options.remoteId && { remoteId: options.remoteId }),
    loadedAt: new Date().toISOString(),
    inventory: {
      companies: companies.length,
      apDocuments: apInbox.length,
      apByChannel,
      arBillingItems: billing.length,
      arRemittanceFiles: arInbox.remittances.length,
      arNotices: arInbox.notices.length,
      bankAccounts: new Set(bankStatements.map((s) => s.account)).size,
      statementsByFormat,
      journalMonths,
      journalBytes: byPath.get(JOURNAL_PATH)?.size ?? 0,
      hasGolden: golden !== null,
      files: files.length,
      bytes: files.reduce((s, f) => s + f.size, 0),
      warnings,
    },
  }
  return { meta, core, rawBank, journal }
}
