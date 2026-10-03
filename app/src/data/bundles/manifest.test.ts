import { normalizeManifest } from './manifest'

describe('normalizeManifest', () => {
  it('keeps the app manifest as is', () => {
    expect(normalizeManifest({ run_id: 'r1', runtime_s: 12 })).toEqual({ run_id: 'r1', runtime_s: 12 })
  })

  it('maps the backend execution report (schema_version 1)', () => {
    const report = {
      schema_version: 1,
      run_id: 'b6f1',
      command: ['kalmora', 'close'],
      calls: [
        { provider: 'anthropic', model: 'claude-opus-5', input_tokens: 1000, output_tokens: 200, estimated_cost: '0.01', pricing: { currency: 'USD' } },
        { provider: 'anthropic', model: 'claude-opus-5', input_tokens: 500, output_tokens: 100, estimated_cost: '0.005', pricing: { currency: 'USD' } },
        { provider: 'typesafe', model: 'jev-1.13.0', input_tokens: 300, output_tokens: null, estimated_cost: null, pricing: null },
      ],
      started_at: '2026-10-03T10:00:00Z',
      ended_at: '2026-10-03T10:05:00Z',
      elapsed_seconds: 300,
      status: 'completed',
      cost: { status: 'unknown', total: null, estimated_by_currency: { USD: '0.015' }, unknown_calls: 1 },
    }
    const m = normalizeManifest(report)!
    expect(m.run_id).toBe('b6f1')
    expect(m.runtime_s).toBe(300)
    expect(m.cost_usd_total).toBeCloseTo(0.015)
    expect(m.models).toEqual([
      { provider: 'anthropic', name: 'claude-opus-5', calls: 2, input_tokens: 1500, output_tokens: 300, cost_usd: 0.015 },
      { provider: 'typesafe', name: 'jev-1.13.0', calls: 1, input_tokens: 300, output_tokens: 0, cost_usd: 0 },
    ])
  })

  it('reports zero cost for runs without LLM calls', () => {
    const m = normalizeManifest({ schema_version: 1, run_id: 'x', calls: [], cost: { status: 'no_llm', total: '0', estimated_by_currency: {}, unknown_calls: 0 } })
    expect(m?.cost_usd_total).toBe(0)
  })
})
