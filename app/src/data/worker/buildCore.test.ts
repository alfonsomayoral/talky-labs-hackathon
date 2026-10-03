// @vitest-environment node
import { describe, expect, it } from 'vitest'
import type { DatasetApi, TrialBalanceRow } from '@/domain/types'
import { fileSystemSource } from '../sources/fileSystemSource'
import { DEV_PHASE, TEST_PHASE, dirFiles, hasDev, hasTest } from '../testing/nodeData'
import { openBackend } from './backend'

const timings: Record<string, number> = {}
const timed = async <T>(label: string, fn: () => Promise<T>): Promise<T> => {
  const t = performance.now()
  const out = await fn()
  timings[label] = Math.round(performance.now() - t)
  return out
}

describe.skipIf(!hasDev)('buildCore + worker backend on phase_dev', async () => {
  // The selection is the parent folder (`participant/`): the phase root must be detected.
  const files = hasDev ? await dirFiles(`${DEV_PHASE}/..`, 'participant') : []
  const phases: string[] = []
  const api: DatasetApi = hasDev
    ? await timed('core', () => openBackend(fileSystemSource(files), { onProgress: (p) => phases.push(p.phase) }))
    : (null as never)

  it('detects the phase root, month and inventory', () => {
    const { meta, core } = api
    expect(meta.name).toBe('phase_dev')
    expect(meta.id).toBe('phase_dev-2026-07')
    expect(meta.month).toBe('2026-07')
    expect(meta.sourceKind).toBe('folder')
    expect(meta.inventory).toMatchObject({
      companies: 7,
      apDocuments: 305,
      arBillingItems: 26,
      bankAccounts: 12,
      hasGolden: true,
      statementsByFormat: { n43: 36, camt053: 4, csv: 8 },
    })
    expect(meta.inventory.journalMonths[0]).toBe('2024-09')
    expect(meta.inventory.journalMonths.at(-1)).toBe('2026-07')
    expect(meta.inventory.warnings).toEqual([])
    expect(core.tasks.ap_documents).toHaveLength(305)
    expect(core.tasks.ar_billing_items).toHaveLength(26)
    expect(core.tasks.ar_receipts).toHaveLength(32)
    expect(core.tasks.bank_accounts).toHaveLength(12)
    expect(new Set(phases)).toEqual(new Set(['Listando ficheros', 'Leyendo tareas', 'Leyendo maestros', 'Leyendo bandeja', 'Leyendo extractos', 'Leyendo golden', 'Leyendo diario']))
  })

  it('loads every core field', () => {
    const { core } = api
    expect(core.vendors.length).toBe(225)
    expect(core.chartOfAccounts.length).toBe(97)
    expect(core.purchaseOrders.length).toBe(655)
    expect(core.apInvoices.length).toBe(4207)
    expect(core.fxRates.length).toBe(2365)
    expect(core.taxCodes.tax_codes.S21.rate).toBe(2100)
    expect(core.intercompanyAgreements.loan.lender).toBeTruthy()
    const doc = core.apInbox.find((d) => d.docId === 'API004093')!
    expect(doc.message.channel).toBe('email')
    expect(doc.files).toEqual(['inbox/ap/API004093/factura_EG-019592.pdf'])
    const item = core.arInbox.billing.find((b) => b.item === 'BILL-CT-1200-AL01-202607')!
    expect(item.meta?.contract).toBe('CT-1200-AL01')
    expect(item.files).toEqual(['inbox/ar/billing/BILL-CT-1200-AL01-202607/documento.pdf'])
    expect(core.arInbox.remittances.length).toBeGreaterThan(0)
    expect(core.bankStatements).toHaveLength(48)
    const bin = core.bankStatements.find((s) => s.account === 'BIN-1100' && s.month === '2026-07')!
    expect(bin.format).toBe('n43')
    expect(bin.lines).toHaveLength(37)
    expect(bin.closing).toBe(bin.opening! + bin.lines.reduce((s, l) => s + l.amount, 0))
    expect(core.golden?.deliverables.ap).toHaveLength(305)
    expect(core.golden?.summary?.ar_receipts).toBe(32)
  })

  it('computes the recorded trial balance equal to golden/trial_balance_recorded.jsonl', async () => {
    const tb = await timed('recordedTB', () => api.recordedTrialBalance())
    const key = (r: TrialBalanceRow) => `${r.company}/${r.account}`
    expect(tb.map(key)).toEqual(api.core.golden!.trialBalanceRecorded.map(key))
    expect(tb).toEqual(api.core.golden!.trialBalanceRecorded)
  })

  it('queries the journal with filters and pagination', async () => {
    const all = await api.queryJournal({})
    expect(all.total).toBe(36743)
    expect(all.entries).toHaveLength(100)
    const bank = await api.queryJournal({ company: '1100', account: '57200001', from: '2026-07', to: '2026-07', limit: 5 })
    expect(bank.total).toBeGreaterThan(0)
    expect(bank.entries.every((e) => e.company === '1100' && e.posting_date.startsWith('2026-07') && e.lines.some((l) => l.account === '57200001'))).toBe(true)
    const page2 = await api.queryJournal({ company: '1100', account: '57200001', from: '2026-07', to: '2026-07', offset: 5, limit: 5 })
    expect(page2.entries[0]?.id).not.toBe(bank.entries[0].id)
    const prefix = await api.queryJournal({ accountPrefix: '4009', company: '1100', limit: 1 })
    expect(prefix.entries[0].lines.some((l) => l.account.startsWith('4009'))).toBe(true)
    const text = await api.queryJournal({ text: 'apertura', limit: 50 })
    expect(text.entries.every((e) => e.source === 'OPENING')).toBe(true)
    const [entry] = await api.getJournalEntries([`${bank.entries[0].id}#2`, 'nope'])
    expect(entry.id).toBe(bank.entries[0].id)
  })

  it('serves goods receipts lazily, raw bank details and files', async () => {
    const all = await api.goodsReceipts()
    expect(all).toHaveLength(21699)
    const po = await api.goodsReceipts({ po: all[0].po })
    expect(po.every((g) => g.po === all[0].po)).toBe(true)
    const raw = await api.rawBankDetails('BIN-1100', '2026-07')
    expect(raw).toHaveLength(37)
    expect(raw[0].bank_line).toBe('BL0004155')
    expect((await api.listFiles('tasks/')).map((f) => f.path).sort()).toHaveLength(6)
    const pdf = await api.readFile('inbox/ap/API004093/factura_EG-019592.pdf')
    expect(pdf.type).toBe('application/pdf')
    expect(new TextDecoder().decode(new Uint8Array(await pdf.slice(0, 4).arrayBuffer()))).toBe('%PDF')
    expect(await api.readText('bank/BIN-1100/2026-07.n43')).toContain('DIPUTACIÓN')
  })

  it('reports timings', () => {
    console.info(`[perf] phase_dev core ${timings.core} ms · recorded TB (journal index) ${timings.recordedTB} ms`)
  })
})

describe.skipIf(!hasTest)('buildCore on phase_test (no golden)', () => {
  it('loads September without golden and without warnings', async () => {
    const api = await openBackend(fileSystemSource(await dirFiles(TEST_PHASE, 'phase_test')))
    expect(api.meta.month).toBe('2026-09')
    expect(api.meta.inventory).toMatchObject({ apDocuments: 297, arBillingItems: 25, bankAccounts: 12, hasGolden: false })
    expect(api.meta.inventory.arNotices).toBe(2)
    expect(api.meta.inventory.warnings).toEqual([])
    expect(api.core.golden).toBeNull()
    expect((await api.recordedTrialBalance()).length).toBeGreaterThan(200)
  })
})
