import type { DatasetCore, DatasetMeta, DerivedRun, RunBundle, TrialBalanceRow } from '@/domain/types'
import { deriveRun, sortAttention } from '@/engine'
import { devPhase, goldenRun, loadCore, loadGolden } from '@/engine/test-utils/phase'
import type { Override } from '@/features/attention/overridesStore'
import { fixtureCore, fixtureRun } from '@/features/item/kit/testing/fixture'
import { reasoningSummary, itemRows } from '@/features/item/kit'
import { attentionSummary, balanceSummary, banksControl, eurConverter } from '@/features/overview/model'
import { pendingAttentionItems } from '@/shell/attentionBadge'
import { itemEntries } from '@/engine'
import { answerLocally, PRESET_QUESTIONS } from './local'
import type { AssistantAnswer, AssistantCard, AssistantContext, MetricDatum } from './types'

const meta = (month: string) => ({ id: 'fixture', name: 'Fixture', month }) as DatasetMeta

function context(core: DatasetCore, run: RunBundle, recorded: TrialBalanceRow[] | null = null, overrides: Override[] = []): AssistantContext {
  return { data: deriveRun(core, run, recorded), core, meta: meta(core.tasks.close.month), run, overrides, mode: 'fast' }
}

const card = <T extends AssistantCard['type']>(a: AssistantAnswer, type: T) => a.cards.find((c): c is Extract<AssistantCard, { type: T }> => c.type === type)
const metric = (a: AssistantAnswer, label: string): MetricDatum['value'] | undefined => card(a, 'metric')?.metrics.find((m) => m.label === label)?.value
const citedItems = (a: AssistantAnswer) => a.citations.flatMap((c) => ('item' in c ? [c.item] : []))

/** Every item an answer shows must exist in the run, so it opens in the side panel. */
function expectItemsOpen(a: AssistantAnswer, data: DerivedRun) {
  const shown = [...citedItems(a), ...a.cards.flatMap((c) => (c.type === 'items' ? c.items.map((i) => i.item) : c.type === 'reasoning' ? [c.item] : []))]
  for (const id of shown) expect(data.itemsById.has(id), id).toBe(true)
}

describe('answerLocally on the fixture', () => {
  const core = fixtureCore()
  const run = fixtureRun()
  const ctx = context(core, run)
  const toEur = eurConverter(core.companies, core.fxRates, '2026-07')

  it('the month summary uses the overview figures', () => {
    const a = answerLocally(PRESET_QUESTIONS[0], ctx)
    expect(a.intent).toBe('summary')
    const att = attentionSummary(ctx.data.attention, ctx.data.itemsById, toEur)
    expect(metric(a, 'En atención')).toEqual({ kind: 'number', value: att.count })
    expect(card(a, 'metric')?.metrics.find((m) => m.label === 'En atención')?.delta).toBeDefined()
    const auto = ctx.data.stats.byStatus.AUTO ?? 0
    expect(metric(a, 'Autonomía')).toEqual({ kind: 'percent', value: auto / ctx.data.stats.items })
    expect(a.text).toContain(`${auto} de ${ctx.data.stats.items} partidas`)
    expectItemsOpen(a, ctx.data)
  })

  it('what to review: pending attention net of human overrides, in EUR', () => {
    const first = sortAttention(ctx.data.attention)[0]
    const overrides: Override[] = [{ runId: run.id, attention_id: first.attention_id || null, item: first.item, action: 'ACCEPT', decision: null, note: null, user: 'u', ts: '' }]
    const withOverride = { ...ctx, overrides }
    const a = answerLocally(PRESET_QUESTIONS[1], withOverride)
    const pending = pendingAttentionItems(ctx.data.attention, overrides)
    expect(pending.length).toBe(ctx.data.attention.length - 1)
    expect(metric(a, 'Pendientes')).toEqual({ kind: 'number', value: pending.length })
    expect(metric(a, 'Importe pendiente')).toEqual({ kind: 'money', cents: Math.round(attentionSummary(pending, ctx.data.itemsById, toEur).impactEur), currency: 'EUR' })
    const items = card(a, 'items')!.items.map((i) => i.item)
    expect(items[0]).toBe(sortAttention(pending)[0].item)
    expectItemsOpen(a, ctx.data)
  })

  it('balance without the journal summed says so; with it, uses balanceSummary', () => {
    expect(answerLocally(PRESET_QUESTIONS[2], ctx).text).toMatch(/sumando el diario/)
    const recorded: TrialBalanceRow[] = [{ company: '1000', account: '60000000', balance: 0 } as unknown as TrialBalanceRow]
    const withTb = context(core, run, recorded)
    const a = answerLocally(PRESET_QUESTIONS[2], withTb)
    const b = balanceSummary(withTb.data.trialBalance!, toEur)
    const movement = card(a, 'table')!
    expect(movement.rows.map((r) => r[1])).toEqual(b.movement.map((m) => ({ kind: 'money', amounts: [{ cents: Math.round(m.amountEur), currency: 'EUR' }] })))
    expect(a.text).toMatch(/Sin golden/)
  })

  it('process answer carries the process map and the policy articles', () => {
    const a = answerLocally(PRESET_QUESTIONS[3], ctx)
    expect(card(a, 'process')).toEqual({ type: 'process', task: 'ap' })
    expect(a.text).toMatch(/^Bandeja de proveedores: 8 partidas/)
    expect(a.citations).toContainEqual({ policy_ref: '§2.2.5' })
    expectItemsOpen(a, ctx.data)
  })

  it('explains an item by id with its reasoning', () => {
    const a = answerLocally('Explica ap:A4', ctx)
    const r = card(a, 'reasoning')!
    expect(r.item).toBe('ap:A4')
    const item = ctx.data.itemsById.get('ap:A4')!
    expect(r.headline).toBe(reasoningSummary({ item, rows: itemRows(run, item), core, entries: itemEntries(core, run, item.id) }).headline)
    expect(r.steps.length).toBeGreaterThan(0)
    expect(a.citations[0]).toEqual({ item: 'ap:A4' })
    expect(answerLocally('Explica XYZ999999', ctx).text).toMatch(/No encuentro XYZ999999/)
  })

  it('an unknown id suggests one that exists in the active run', () => {
    const suggested = answerLocally('Explica XYZ999999', ctx).text.match(/«Explica ([^»]+)»/)?.[1]
    expect(suggested).toBeDefined()
    expect(answerLocally(`Explica ${suggested}`, ctx).intent).toBe('explain')
    expect(card(answerLocally(`Explica ${suggested}`, ctx), 'reasoning')).toBeDefined()
  })

  it('bank account status agrees with the close controls', () => {
    const a = answerLocally('¿Cómo está BIN-1000?', ctx)
    const control = banksControl(core.tasks.bank_accounts, run.deliverables.bank_rec, ctx.data.items)
    expect(metric(a, 'Estado')).toEqual({ kind: 'text', text: control.unexplained.includes('BIN-1000') ? 'Diferencias sin explicar' : 'Conciliada' })
    expect(metric(a, 'Casaciones')).toEqual({ kind: 'number', value: 2 })
    expect(a.links[0].to).toBe('/tareas/bancos/BIN-1000')
    expectItemsOpen(a, ctx.data)
    expect(answerLocally('¿Y BIN-9999?', ctx).text).toMatch(/No encuentro la cuenta BIN-9999/)
  })

  it('cost reads the manifest, or says there is none', () => {
    expect(answerLocally('¿Cuánto ha costado?', ctx).text).toMatch(/no trae manifest.json/)
    const manifest = { run_id: 'r', runtime_s: 1300, cost_usd_total: 3.51, models: [{ provider: 'anthropic', name: 'claude', calls: 61, input_tokens: 410000, output_tokens: 52000, cost_usd: 3.35 }] }
    const a = answerLocally('¿Cuánto ha costado?', context(core, fixtureRun({ manifest })))
    expect(metric(a, 'Coste')).toEqual({ kind: 'money', cents: 351, currency: 'USD' })
    expect(metric(a, 'Llamadas')).toEqual({ kind: 'number', value: 61 })
  })
})

const fixture = await devPhase()

describe.skipIf(!fixture)('answerLocally on golden (phase_dev)', () => {
  const golden = fixture ? loadGolden(fixture) : null!
  const core = fixture ? loadCore(fixture, golden) : null!
  const run = fixture ? goldenRun(golden) : null!
  const ctx = fixture ? context(core, run, golden.trialBalanceRecorded) : null!
  const toEur = fixture ? eurConverter(core.companies, core.fxRates, core.tasks.close.month) : null!

  it('the four preset questions answer with the Resumen and Atención figures', () => {
    const [summary, review, balance, process] = PRESET_QUESTIONS.map((q) => answerLocally(q, ctx))
    const att = attentionSummary(ctx.data.attention, ctx.data.itemsById, toEur)
    expect(metric(summary, 'En atención')).toEqual({ kind: 'number', value: att.count })
    expect(metric(review, 'Pendientes')).toEqual({ kind: 'number', value: att.count })
    expect(metric(review, 'Importe pendiente')).toEqual({ kind: 'money', cents: Math.round(att.impactEur), currency: 'EUR' })
    const b = balanceSummary(ctx.data.trialBalance!, toEur)
    expect(metric(balance, 'Hueco cerrado')).toEqual({ kind: 'percent', value: b.score })
    expect(metric(balance, 'Hueco registrado')).toEqual({ kind: 'money', cents: Math.round(b.gapRecordedEur!), currency: 'EUR' })
    expect(metric(balance, 'Hueco después')).toEqual({ kind: 'money', cents: Math.round(b.gapAfterEur!), currency: 'EUR' })
    expect(process.text).toMatch(/^Bandeja de proveedores: 305 partidas/)
    for (const a of [summary, review, balance, process]) expectItemsOpen(a, ctx.data)
  })

  it('«Explica API004128» returns its reasoning', () => {
    const a = answerLocally('Explica API004128', ctx)
    const r = card(a, 'reasoning')!
    expect(r.item).toBe('ap:API004128')
    expect(r.headline.length).toBeGreaterThan(10)
    expect(r.steps.some((s) => s.kind === 'CASCADE')).toBe(true)
    expect(a.text).toContain('API004128')
  })
})
