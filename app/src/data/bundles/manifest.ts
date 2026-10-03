// Accepts both the app's RunManifest (CONTRACT.md §1.1) and the backend's execution
// report (`outputs/runs/<uuid>.json`, schema_version 1, written by kalmora.runlog).

import type { ModelUsage, RunManifest } from '@/domain/types'

interface BackendCall {
  provider: string
  model: string
  input_tokens: number | null
  output_tokens: number | null
  estimated_cost: string | null
  pricing: { currency?: string } | null
}

interface BackendRunReport {
  schema_version: number
  run_id: string
  command?: string[]
  input_metadata?: Record<string, unknown>
  calls: BackendCall[]
  started_at?: string
  ended_at?: string
  elapsed_seconds?: number
  status?: string
  cost?: { status: string; total: string | null; estimated_by_currency: Record<string, string>; unknown_calls: number }
}

const isBackendReport = (raw: unknown): raw is BackendRunReport =>
  typeof raw === 'object' && raw !== null && 'schema_version' in raw && Array.isArray((raw as { calls?: unknown }).calls)

function fromBackendReport(r: BackendRunReport): RunManifest {
  const models = new Map<string, ModelUsage>()
  for (const c of r.calls) {
    const key = `${c.provider}/${c.model}`
    const m = models.get(key) ?? { provider: c.provider, name: c.model, calls: 0, input_tokens: 0, output_tokens: 0, cost_usd: 0 }
    m.calls += 1
    m.input_tokens += c.input_tokens ?? 0
    m.output_tokens += c.output_tokens ?? 0
    if (c.estimated_cost !== null && (c.pricing?.currency ?? 'USD') === 'USD') m.cost_usd += Number(c.estimated_cost)
    models.set(key, m)
  }
  const usd = r.cost?.estimated_by_currency?.USD
  return {
    run_id: r.run_id,
    started_at: r.started_at,
    finished_at: r.ended_at,
    runtime_s: r.elapsed_seconds,
    models: [...models.values()],
    cost_usd_total: r.cost?.status === 'no_llm' ? 0 : usd !== undefined ? Number(usd) : undefined,
    status: r.status,
    cost_status: r.cost?.status,
    command: r.command,
    input_metadata: r.input_metadata,
  }
}

export function normalizeManifest(raw: unknown): RunManifest | null {
  if (typeof raw !== 'object' || raw === null) return null
  if (isBackendReport(raw)) return fromBackendReport(raw)
  return raw as RunManifest
}
