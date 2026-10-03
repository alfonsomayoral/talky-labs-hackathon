import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import type { DatasetApi, DerivedRun, FileValidation, RunBundle, TaskKey, ValidationReport, WorkItem } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { computeStats } from '@/engine'
import { Overview } from './OverviewPage'

const item = (id: string, task: TaskKey, status: WorkItem['status'], outcome: string): WorkItem => ({
  id,
  task,
  key: id.slice(id.indexOf(':') + 1),
  company: '1000',
  title: id,
  counterparty: null,
  amount: 100,
  currency: 'EUR',
  date: null,
  status,
  outcome,
  reasons: [],
  confidence: null,
  provenance: 'RULE',
  policyRefs: [],
  evidence: [],
  tbImpact: 0,
  rowIndex: 0,
})

const file = (task: TaskKey): FileValidation => ({
  task,
  present: true,
  rows: 1,
  expected: null,
  missingKeys: [],
  duplicateKeys: [],
  extraKeys: [],
  unbalancedEntries: [],
  nonIntegerAmounts: 0,
  unknownAccounts: [],
  invalidValues: [],
  errors: [],
  warnings: [],
})

describe('Overview of an agent run without golden', () => {
  const items = [item('ap:A1', 'ap', 'AUTO', 'POST'), item('ap:A2', 'ap', 'BLOCKED', 'HOLD'), item('bank_rec:B1/L1', 'bank_rec', 'AUTO', 'MATCH')]
  const validation: ValidationReport = { ok: true, files: Object.fromEntries(TASK_KEYS.map((k) => [k, file(k)])) as ValidationReport['files'] }
  const data: DerivedRun = {
    runId: 'sep',
    items,
    itemsById: new Map(items.map((i) => [i.id, i])),
    attention: [],
    events: [],
    eventsByItem: new Map(),
    eventsSynthesized: true,
    validation,
    trialBalance: {
      rows: [{ company: '1000', account: '55500000', recorded: -500, delta: { ar_cash: 500 }, after: 0, truth: null }],
      gapRecorded: null,
      gapAfter: null,
      score: null,
      movementByTask: Object.fromEntries(TASK_KEYS.map((k) => [k, 0])) as Record<TaskKey, number>,
    },
    score: null,
    stats: computeStats(items, [], validation),
  }
  const api = {
    meta: { id: 'test', name: 'phase_test', month: '2026-09', inventory: { companies: 7, hasGolden: false } },
    core: { companies: [{ code: '1000', currency: 'EUR' }], fxRates: [], tasks: { bank_accounts: ['B1'] } },
  } as unknown as DatasetApi
  const run = {
    id: 'sep',
    datasetId: 'test',
    source: 'import',
    label: 'Septiembre v3',
    createdAt: '2026-10-03T10:00:00Z',
    manifest: { run_id: 'sep', cost_usd_total: 12.4, runtime_s: 1300 },
    deliverables: { ap: [], ar_billing: [], ar_cash: [], bank_rec: [{ account: 'B1', company: '1000', matches: [], unmatched_bank: [], unmatched_book: [], adjustments: [] }], ic: [], close: [] },
    present: Object.fromEntries(TASK_KEYS.map((k) => [k, true])),
    events: null,
    attention: null,
  } as unknown as RunBundle

  it('credits the agent and falls back where golden is needed', () => {
    render(
      <MemoryRouter>
        <Overview data={data} api={api} run={run} />
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('El agente ha resuelto 2 de 3 partidas sin intervención.')
    expect(screen.getByText('Cierre de septiembre de 2026 · Grupo Kalmora · 7 sociedades')).toBeInTheDocument()
    expect(screen.getByText('Movimiento del balance')).toBeInTheDocument()
    expect(screen.getByText('Sin golden no hay nota')).toBeInTheDocument()
    expect(screen.getByText('4/4 a cero')).toBeInTheDocument()
    expect(screen.getByText('1/1')).toBeInTheDocument()
    expect(screen.getByText('Nada pendiente')).toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: /^ap:A2/ })).toHaveLength(1)
  })
})
