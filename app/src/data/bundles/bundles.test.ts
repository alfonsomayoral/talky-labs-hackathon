// @vitest-environment node
import { strToU8, zipSync } from 'fflate'
import { describe, expect, it } from 'vitest'
import { TASK_KEYS, type DatasetMeta, type Golden } from '@/domain/types'
import { DEV_PHASE, hasDev, readJsonl } from '../testing/nodeData'
import { bundleFromFiles, runFilesFromInput } from './bundle'
import { goldenRun, stripGolden } from './golden'

const meta = { id: 'phase_dev-2026-07', name: 'phase_dev', month: '2026-07' } as DatasetMeta
const jsonl = (rows: object[]) => rows.map((r) => JSON.stringify(r)).join('\n') + '\n'
const pf = (path: string, content: string) => ({ path, file: new Blob([content]) })
const fileAt = (path: string, content: string | Uint8Array<ArrayBuffer>) => {
  const f = new File([content], path.split('/').pop()!)
  if (path.includes('/')) Object.defineProperty(f, 'webkitRelativePath', { value: path })
  return f
}

describe('golden run', () => {
  const golden: Golden = {
    deliverables: {
      ap: [{ doc_id: 'A1', decision: 'POST', cases: ['X'] }],
      ar_billing: [{ billing_item: 'B1', expected: 'INVOICE' }],
      ar_cash: [],
      bank_rec: [],
      ic: [{ pair: ['1000', '1100'], cause: 'INVOICE_IN_TRANSIT', note: 'internal', detail: 'kept', adjustment: [] }],
      close: [{ type: 'ACCRUAL', company: '1200', amount: 5, je: 'J1', estimate: true, journal_entry: null }],
    } as unknown as Golden['deliverables'],
    trialBalanceTruth: [],
    trialBalanceRecorded: [],
    summary: null,
  }

  it('strips the internal fields per task and keeps the rest', () => {
    const d = stripGolden(golden)
    expect(d.ap[0]).toEqual({ doc_id: 'A1', decision: 'POST' })
    expect(d.ic[0]).toEqual({ pair: ['1000', '1100'], cause: 'INVOICE_IN_TRANSIT', detail: 'kept', adjustment: [] })
    expect(d.close[0]).toEqual({ type: 'ACCRUAL', company: '1200', amount: 5, journal_entry: null })
    expect(golden.deliverables.ap[0]).toHaveProperty('cases')
  })

  it('builds a deterministic reference run with every deliverable present', () => {
    const run = goldenRun(meta, golden)
    expect(run).toMatchObject({ id: 'phase_dev-2026-07.golden', datasetId: meta.id, source: 'golden', label: 'Referencia (golden)', events: null, attention: null })
    expect(Object.values(run.present).every(Boolean)).toBe(true)
  })

  it.skipIf(!hasDev)('strips the real golden', () => {
    const real = { deliverables: Object.fromEntries(TASK_KEYS.map((k) => [k, readJsonl(`${DEV_PHASE}/golden/${k}.jsonl`)])) } as unknown as Golden
    const d = stripGolden(real)
    expect(d.ap).toHaveLength(305)
    expect(d.ap.some((r) => 'cases' in r)).toBe(false)
    expect(d.close.some((r) => 'je' in r || 'estimate' in r)).toBe(false)
    expect(d.ic.some((r) => 'note' in r)).toBe(false)
  })
})

describe('run import', () => {
  it('imports loose JSONL files and marks the missing ones as absent', async () => {
    const { files, name } = await runFilesFromInput([fileAt('ap.jsonl', jsonl([{ doc_id: 'A1' }])), fileAt('bank_rec.jsonl', jsonl([{ account: 'BIN-1000' }]))])
    expect(name).toBeNull()
    const run = await bundleFromFiles(files, { datasetId: meta.id, source: 'import', label: 'Mi prueba' })
    expect(run.present).toEqual({ ap: true, ar_billing: false, ar_cash: false, bank_rec: true, ic: false, close: false })
    expect(run.deliverables.ap).toEqual([{ doc_id: 'A1' }])
    expect(run.deliverables.ar_cash).toEqual([])
    expect(run.label).toBe('Mi prueba')
    expect(run.manifest).toBeNull()
    expect(run.events).toBeNull()
  })

  it('imports a bundle folder with manifest and trace', async () => {
    const input = [
      fileAt('dev-r003/manifest.json', JSON.stringify({ run_id: 'dev-r003', month: '2026-07' })),
      fileAt('dev-r003/deliverables/ap.jsonl', jsonl([{ doc_id: 'A1' }])),
      fileAt('dev-r003/deliverables/ic.jsonl', ''),
      fileAt('dev-r003/trace/events.jsonl', jsonl([{ event_id: 'e1', item: 'ap:A1' }])),
      fileAt('dev-r003/trace/attention.jsonl', jsonl([{ attention_id: 'att-1', item: 'ap:A1' }])),
      fileAt('dev-r003/.DS_Store', 'x'),
    ]
    const { files, name } = await runFilesFromInput(input)
    const run = await bundleFromFiles(files, { datasetId: meta.id, source: 'import', name })
    expect(run.id).toBe('phase_dev-2026-07.dev-r003')
    expect(run.label).toBe('dev-r003')
    expect(run.present.ap).toBe(true)
    expect(run.present.ic).toBe(true)
    expect(run.present.close).toBe(false)
    expect(run.events).toHaveLength(1)
    expect(run.attention?.[0].attention_id).toBe('att-1')
  })

  it('imports a zip of a bundle', async () => {
    const zip = zipSync({
      'out/deliverables/close.jsonl': strToU8(jsonl([{ type: 'ACCRUAL', company: '1200', amount: 1 }])),
      'out/manifest.json': strToU8('{"run_id":"z1"}'),
    })
    const { files, name } = await runFilesFromInput(fileAt('resultados.zip', zip))
    expect(name).toBe('resultados')
    const run = await bundleFromFiles(files, { datasetId: meta.id, source: 'import', name })
    expect(run.id).toBe('phase_dev-2026-07.z1')
    expect(run.present.close).toBe(true)
    expect(run.deliverables.close).toHaveLength(1)
  })

  it('rejects input without any deliverable and reports bad JSON with the file name', async () => {
    await expect(bundleFromFiles([pf('notes.txt', 'x')], { datasetId: meta.id, source: 'import' })).rejects.toThrow(/ninguna de las 6/)
    await expect(bundleFromFiles([pf('ap.jsonl', '{bad')], { datasetId: meta.id, source: 'import' })).rejects.toThrow(/ap\.jsonl.*línea 1/)
  })
})
