// Loads a phase folder from disk for engine tests, independently of the data layer.
// Only what the engine reads is loaded; the journal and goods receipts are skipped.

import type {
  ApInboxDoc,
  BankLine,
  BankStatement,
  DatasetCore,
  Deliverables,
  Golden,
  InboxMessage,
  RunBundle,
  TaskKey,
  TrialBalanceRow,
} from '@/domain/types'
import { GOLDEN_INTERNAL_FIELDS, TASK_KEYS } from '@/domain/types'
import { nodeEnv, type NodeEnv } from './node'

export interface PhaseFixture {
  node: NodeEnv
  /** Absolute path of phase_dev. */
  phaseDir: string
  /** Absolute path of score.py (next to the phase folder). */
  scorePy: string
}

/** phase_dev resolved from KALMORA_DEV_PHASE or `<app>/../../participant/phase_dev` (same layout as .env.local). */
export async function devPhase(): Promise<PhaseFixture | null> {
  const node = await nodeEnv()
  const phaseDir = node.env.KALMORA_DEV_PHASE ?? node.path.resolve(node.cwd, '../../participant/phase_dev')
  const scorePy = node.path.resolve(phaseDir, '../score.py')
  if (!node.fs.existsSync(node.path.join(phaseDir, 'golden'))) return null
  return { node, phaseDir, scorePy }
}

export function hasPython(node: NodeEnv): boolean {
  const r = node.cp.spawnSync('python3', ['--version'], { encoding: 'utf8' })
  return r.status === 0
}

export function readJsonl<T = unknown>(node: NodeEnv, file: string): T[] {
  if (!node.fs.existsSync(file)) return []
  return node.fs
    .readFileSync(file, 'utf8')
    .split('\n')
    .filter((l) => l.trim())
    .map((l) => JSON.parse(l) as T)
}

const readJson = <T>(node: NodeEnv, file: string): T => JSON.parse(node.fs.readFileSync(file, 'utf8')) as T

export function loadGolden(f: PhaseFixture): Golden {
  const { node, phaseDir } = f
  const dir = node.path.join(phaseDir, 'golden')
  const deliverables = {} as Record<TaskKey, unknown[]>
  for (const k of TASK_KEYS) deliverables[k] = readJsonl(node, node.path.join(dir, `${k}.jsonl`))
  return {
    deliverables: deliverables as unknown as Deliverables,
    trialBalanceTruth: readJsonl<TrialBalanceRow>(node, node.path.join(dir, 'trial_balance_truth.jsonl')),
    trialBalanceRecorded: readJsonl<TrialBalanceRow>(node, node.path.join(dir, 'trial_balance_recorded.jsonl')),
    summary: null,
  }
}

/** Golden opened as a run (internal fields stripped), like the data layer's createGoldenRun. */
export function goldenRun(golden: Golden): RunBundle {
  const deliverables = {} as Record<TaskKey, unknown[]>
  for (const k of TASK_KEYS) {
    deliverables[k] = golden.deliverables[k].map((row) => {
      const copy = { ...(row as Record<string, unknown>) }
      for (const f of GOLDEN_INTERNAL_FIELDS[k]) delete copy[f]
      return copy
    })
  }
  return {
    id: 'golden',
    datasetId: 'dev',
    source: 'golden',
    label: 'Referencia',
    createdAt: '2026-10-03T10:00:00Z',
    manifest: null,
    deliverables: deliverables as unknown as Deliverables,
    present: Object.fromEntries(TASK_KEYS.map((k) => [k, true])) as Record<TaskKey, boolean>,
    events: null,
    attention: null,
  }
}

export function loadCore(f: PhaseFixture, golden: Golden | null): DatasetCore {
  const { node, phaseDir } = f
  const p = (...parts: string[]) => node.path.join(phaseDir, ...parts)
  const erp = (name: string) => readJsonl(node, p('erp', name)) as never
  const bankStatements: BankStatement[] = []
  for (const account of node.fs.readdirSync(p('bank')).filter((d) => !d.startsWith('.'))) {
    for (const file of node.fs.readdirSync(p('bank', account)).filter((n) => n.endsWith('.lines.jsonl'))) {
      bankStatements.push({
        account,
        month: file.slice(0, 7),
        format: 'n43',
        lines: readJsonl<BankLine>(node, p('bank', account, file)),
        rawPath: null,
      })
    }
  }
  const apInbox: ApInboxDoc[] = node.fs
    .readdirSync(p('inbox', 'ap'))
    .filter((d) => !d.startsWith('.'))
    .map((docId) => {
      const message = readJson<InboxMessage>(node, p('inbox', 'ap', docId, 'message.json'))
      return { docId, message, files: message.attachments.map((a) => `inbox/ap/${docId}/${a}`) }
    })
  return {
    companies: readJson(node, p('erp', 'companies.json')),
    chartOfAccounts: erp('chart_of_accounts.jsonl'),
    taxCodes: readJson(node, p('erp', 'tax_codes.json')),
    costCenters: erp('cost_centers.jsonl'),
    projects: erp('projects.jsonl'),
    vendors: erp('vendors.jsonl'),
    contractorCertificates: erp('contractor_certificates.jsonl'),
    customers: erp('customers.jsonl'),
    salesContracts: erp('sales_contracts.jsonl'),
    purchaseOrders: [],
    openItems: erp('open_items.jsonl'),
    apInvoices: [],
    apDocumentLog: [],
    arInvoices: erp('ar_invoices.jsonl'),
    billingHistory: [],
    promissoryNotes: erp('promissory_notes.jsonl'),
    factoringAssignments: erp('factoring_assignments.jsonl'),
    sepaRemittances: [],
    penaltyNotices: erp('penalty_notices.jsonl'),
    intercompanyAgreements: readJson(node, p('erp', 'intercompany_agreements.json')),
    fxRates: erp('fx_rates.jsonl'),
    bankAccounts: erp('bank_accounts.jsonl'),
    tasks: {
      ap_documents: readJson(node, p('tasks', 'ap_documents.json')),
      ar_billing_items: readJson(node, p('tasks', 'ar_billing_items.json')),
      ar_receipts: readJson(node, p('tasks', 'ar_receipts.json')),
      bank_accounts: readJson(node, p('tasks', 'bank_accounts.json')),
      intercompany: readJson(node, p('tasks', 'intercompany.json')),
      close: readJson(node, p('tasks', 'close.json')),
    },
    apInbox,
    arInbox: { billing: [], remittances: [], notices: [] },
    bankStatements,
    golden,
  }
}

/** Writes rows as `<dir>/<task>.jsonl` (tasks set to null are not written: missing file). */
export function writeSubmission(node: NodeEnv, dir: string, subs: Partial<Record<TaskKey, unknown[] | null>>): void {
  node.fs.mkdirSync(dir, { recursive: true })
  for (const k of TASK_KEYS) {
    const rows = subs[k]
    if (!rows) continue
    node.fs.writeFileSync(node.path.join(dir, `${k}.jsonl`), rows.map((r) => JSON.stringify(r)).join('\n') + (rows.length ? '\n' : ''))
  }
}

/** Runs `python3 score.py <phase> <phase> <dir> --json <out>` and returns its JSON. */
export function runScorePy(f: PhaseFixture, dir: string): Record<string, unknown> {
  const out = f.node.path.join(dir, 'score.out.json')
  const r = f.node.cp.spawnSync('python3', [f.scorePy, f.phaseDir, f.phaseDir, dir, '--json', out], { encoding: 'utf8', timeout: 120_000 })
  if (r.status !== 0) throw new Error(`score.py failed: ${r.stderr || r.error?.message}`)
  return JSON.parse(f.node.fs.readFileSync(out, 'utf8')) as Record<string, unknown>
}
