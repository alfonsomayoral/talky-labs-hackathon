import { describe, expect, it } from 'vitest'
import type { AgentEvent, ItemScore, RunManifest, WorkItem } from '@/domain/types'
import { normalizeManifest } from '@/data/bundles/manifest'
import { confidencePoints, costSummary, expectedCalibrationError, reliabilityBins, taskTimeline, thresholdStats } from './model'

const item = (id: string, confidence: number | null): WorkItem =>
  ({ id, task: id.split(':')[0], key: id.split(':')[1], confidence }) as WorkItem

const score = (id: string, exact: boolean): ItemScore => ({ item: id, score: exact ? 1 : 0, exact, diffs: [] })

const event = (item: string, ts: string, duration_ms?: number): AgentEvent => ({
  event_id: `${item}@${ts}`,
  item,
  seq: 1,
  ts,
  kind: 'CHECK',
  step: 's',
  result: 'PASS',
  summary: '',
  duration_ms,
})

/** Synthetic test package: 20 AP items, well calibrated at 0.95 and over-confident at 0.75. */
function syntheticRun() {
  const items: WorkItem[] = []
  const perItem: Record<string, ItemScore> = {}
  for (let i = 0; i < 10; i++) {
    const id = `ap:HI${i}`
    items.push(item(id, 0.95))
    perItem[id] = score(id, i !== 0) // 9/10 right
  }
  for (let i = 0; i < 10; i++) {
    const id = `ap:LO${i}`
    items.push(item(id, 0.75))
    perItem[id] = score(id, i < 4) // 4/10 right
  }
  items.push(item('ap:NOCONF', null))
  return { items, perItem }
}

describe('costSummary', () => {
  it('reads the backend execution report through the manifest normalizer', () => {
    const manifest = normalizeManifest({
      schema_version: 1,
      run_id: 'r1',
      started_at: '2026-10-03T10:00:00Z',
      ended_at: '2026-10-03T10:05:00Z',
      elapsed_seconds: 300,
      calls: [
        { provider: 'anthropic', model: 'claude', input_tokens: 1000, output_tokens: 200, estimated_cost: '0.50', pricing: { currency: 'USD' } },
        { provider: 'anthropic', model: 'claude', input_tokens: 500, output_tokens: 100, estimated_cost: '0.25', pricing: { currency: 'USD' } },
        { provider: 'typesafe', model: 'jev', input_tokens: 100, output_tokens: null, estimated_cost: '0.01', pricing: null },
      ],
      cost: { status: 'estimated', total: '0.76', estimated_by_currency: { USD: '0.76' }, unknown_calls: 0 },
    })
    const s = costSummary(manifest)
    expect(s.models.map((m) => m.name)).toEqual(['claude', 'jev'])
    expect(s).toMatchObject({ calls: 3, inputTokens: 1600, outputTokens: 300, costUsd: 0.76, runtimeMs: 300_000 })
  })

  it('falls back to the sum of models and the timestamps', () => {
    const s = costSummary({
      run_id: 'r',
      started_at: '2026-10-03T10:00:00Z',
      finished_at: '2026-10-03T10:00:30Z',
      models: [{ provider: 'p', name: 'm', calls: 2, input_tokens: 10, output_tokens: 5, cost_usd: 0.2 }],
    })
    expect(s.costUsd).toBeCloseTo(0.2)
    expect(s.runtimeMs).toBe(30_000)
    expect(costSummary(null)).toMatchObject({ models: [], costUsd: null, runtimeMs: null })
  })
})

describe('taskTimeline', () => {
  it('prefers manifest.tasks and measures from the run start', () => {
    const manifest: RunManifest = {
      run_id: 'r',
      started_at: '2026-10-03T10:00:00Z',
      tasks: {
        ap: { started_at: '2026-10-03T10:00:10Z', finished_at: '2026-10-03T10:01:00Z' },
        bank_rec: { started_at: '2026-10-03T10:01:00Z', finished_at: '2026-10-03T10:02:00Z' },
        ic: { started_at: '2026-10-03T10:03:00Z' },
      },
    }
    const t = taskTimeline(manifest, [event('ar_cash:B1', '2026-10-03T10:00:00Z', 5)])!
    expect(t.source).toBe('manifest')
    expect(t.spans).toEqual([
      { task: 'ap', start: 10_000, end: 60_000 },
      { task: 'bank_rec', start: 60_000, end: 120_000 },
    ])
    expect(t.total).toBe(120_000)
  })

  it('derives spans from events, including the last event duration', () => {
    const t = taskTimeline(null, [
      event('ap:A1', '2026-10-03T10:00:00Z', 100),
      event('ap:A2', '2026-10-03T10:00:02Z', 500),
      event('close:ACCRUAL/1000/V1', '2026-10-03T10:00:03Z'),
      event('bogus', '2026-10-03T10:00:09Z'),
    ])!
    expect(t.source).toBe('events')
    expect(t.spans).toEqual([
      { task: 'ap', start: 0, end: 2500 },
      { task: 'close', start: 3000, end: 3000 },
    ])
  })

  it('has nothing to draw without timing', () => {
    expect(taskTimeline(null, null)).toBeNull()
    expect(taskTimeline(null, [event('ap:A1', '2026-10-03T10:00:00Z'), event('ap:A2', '2026-10-03T10:00:00Z')])).toBeNull()
  })
})

describe('calibration', () => {
  it('bins the synthetic package and measures its calibration error', () => {
    const { items, perItem } = syntheticRun()
    const points = confidencePoints(items, perItem)
    expect(points).toHaveLength(20)

    const bins = reliabilityBins(points)
    const hi = bins[9]
    const lo = bins[7]
    expect(hi).toMatchObject({ count: 10, known: 10, accuracy: 0.9 })
    expect(hi.meanP).toBeCloseTo(0.95)
    expect(lo).toMatchObject({ count: 10, known: 10, accuracy: 0.4 })
    expect(bins.filter((b) => b.count).length).toBe(2)
    // ½·|0,9 − 0,95| + ½·|0,4 − 0,75| = 0,2
    expect(expectedCalibrationError(bins)).toBeCloseTo(0.2)
  })

  it('puts p = 1 in the last bin and keeps counts without golden', () => {
    const points = confidencePoints([item('ap:A', 1), item('ap:B', 0)], null)
    const bins = reliabilityBins(points, 4)
    expect(bins.map((b) => b.count)).toEqual([1, 0, 0, 1])
    expect(bins[3]).toMatchObject({ known: 0, accuracy: null, meanP: 1 })
    expect(expectedCalibrationError(bins)).toBeNull()
  })

  it('splits auto and human work at the threshold', () => {
    const { items, perItem } = syntheticRun()
    const points = confidencePoints(items, perItem)

    const strict = thresholdStats(points, 0.9)
    expect(strict).toMatchObject({ total: 20, auto: 10, toHuman: 10, coverage: 0.5, actualErrors: 1, accuracy: 0.9 })
    expect(strict.expectedErrors).toBeCloseTo(0.5)

    const loose = thresholdStats(points, 0.7)
    expect(loose).toMatchObject({ auto: 20, toHuman: 0, actualErrors: 7, accuracy: 0.65 })

    expect(thresholdStats(confidencePoints(items, null), 0.9)).toMatchObject({ auto: 10, actualErrors: null, accuracy: null })
  })
})
