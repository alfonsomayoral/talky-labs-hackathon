// @vitest-environment node
// The downloaded zip, unzipped and passed through `python3 score.py`, scores what the app shows (100 on golden).
import { strFromU8, unzipSync } from 'fflate'
import type { Deliverables, RunBundle, TaskKey } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { scoreRun } from '@/engine'
import { devPhase, goldenRun, hasPython, loadGolden, runScorePy } from '@/engine/test-utils/phase'
import { buildDeliveryZip, deliveryFolder, deliveryManifest, toJsonl } from './deliveryZip'

const fakeRun = (present: Partial<Record<TaskKey, boolean>>): RunBundle => ({
  id: 'dev.r 1/x',
  datasetId: 'dev',
  source: 'import',
  label: 'r1',
  createdAt: '2026-10-03T10:00:00Z',
  manifest: null,
  deliverables: {
    ap: [{ doc_id: 'API1', decision: 'POST', net: 100, note: 'ñ €' }],
    ar_billing: [],
    ar_cash: [],
    bank_rec: [],
    ic: [{ pair: ['1000', '3100'], cause: 'INTEREST_DAY_COUNT' }],
    close: [],
  } as unknown as Deliverables,
  present: Object.fromEntries(TASK_KEYS.map((t) => [t, !!present[t]])) as Record<TaskKey, boolean>,
  events: null,
  attention: null,
})

describe('delivery zip', () => {
  it('holds the present JSONL byte for byte, the manifest and overrides only when there are any', () => {
    const run = fakeRun({ ap: true, ic: true, close: true })
    const manifest = deliveryManifest(run, { dataset: { id: 'dev', name: 'phase_dev', month: '2026-07' }, overrides: 0, now: 'T' })
    const files = unzipSync(buildDeliveryZip(run, { manifest, overridesJsonl: '' }))
    const root = deliveryFolder(run.id)
    expect(root).toBe('entrega_dev.r-1-x')
    expect(Object.keys(files).sort()).toEqual([`${root}/ap.jsonl`, `${root}/close.jsonl`, `${root}/ic.jsonl`, `${root}/manifest.json`])
    expect(strFromU8(files[`${root}/ap.jsonl`])).toBe('{"doc_id":"API1","decision":"POST","net":100,"note":"ñ €"}\n')
    expect(strFromU8(files[`${root}/close.jsonl`])).toBe('')
    expect(JSON.parse(strFromU8(files[`${root}/manifest.json`]))).toMatchObject({
      run_id: run.id,
      dataset: 'phase_dev',
      month: '2026-07',
      source: 'import',
      files: ['ap.jsonl', 'ic.jsonl', 'close.jsonl'],
      counts: { ap: 1, ic: 1, close: 0 },
      human_overrides: 0,
    })

    const withOverrides = unzipSync(buildDeliveryZip(run, { manifest, overridesJsonl: '{"item":"ap:API1"}' }))
    expect(strFromU8(withOverrides[`${root}/overrides.jsonl`])).toBe('{"item":"ap:API1"}\n')
  })

  it("keeps the backend's manifest fields and records the human overrides", () => {
    const run = { ...fakeRun({ ap: true }), manifest: { run_id: 'r003', cost_usd_total: 3.51, human_overrides: 9 } }
    const m = deliveryManifest(run, { dataset: null, overrides: 2 })
    expect(m).toMatchObject({ run_id: 'r003', dataset: 'dev', cost_usd_total: 3.51, human_overrides: 2, files: ['ap.jsonl'] })
  })
})

const fixture = await devPhase()
const ready = fixture !== null && hasPython(fixture.node)

describe.skipIf(!ready)('delivery zip with score.py', () => {
  it('scores 100 on the golden run, as the app does', () => {
    const f = fixture!
    const golden = loadGolden(f)
    const run = goldenRun(golden)
    const zip = buildDeliveryZip(run, { manifest: deliveryManifest(run, { dataset: null, overrides: 1 }), overridesJsonl: '{"item":"ap:X"}' })

    const tmp = f.node.fs.mkdtempSync(f.node.path.join(f.node.tmpdir, 'kalmora-zip-'))
    try {
      for (const [path, bytes] of Object.entries(unzipSync(zip))) {
        const abs = f.node.path.join(tmp, path)
        f.node.fs.mkdirSync(f.node.path.dirname(abs), { recursive: true })
        f.node.fs.writeFileSync(abs, strFromU8(bytes))
      }
      const dir = f.node.path.join(tmp, deliveryFolder(run.id))
      for (const t of TASK_KEYS) {
        const rows = f.node.fs.readFileSync(f.node.path.join(dir, `${t}.jsonl`), 'utf8')
        expect(rows).toBe(toJsonl(run.deliverables[t]))
      }
      const py = runScorePy(f, dir)
      expect(py.total).toBe(100)
      expect(scoreRun(run, golden).total).toBe(py.total)
    } finally {
      f.node.fs.rmSync(tmp, { recursive: true, force: true })
    }
  })
})
