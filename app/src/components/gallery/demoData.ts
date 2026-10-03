// Synthetic Kalmora-like rows for the component gallery (deterministic, no dataset files).
import type { ItemStatus, Provenance, TaskKey } from '@/domain/types'

export interface DemoRow {
  id: string
  task: TaskKey
  company: string
  counterparty: string
  amount: number
  currency: string
  date: string
  status: ItemStatus
  outcome: string
  provenance: Provenance
  confidence: number | null
}

export const TASK_LABEL: Record<TaskKey, string> = {
  ap: 'AP',
  ar_billing: 'Facturación',
  ar_cash: 'Cobros',
  bank_rec: 'Bancos',
  ic: 'Intragrupo',
  close: 'Cierre',
}

const COMPANIES = ['1000', '1100', '1100', '1100', '1200', '1300', '1910', '2100', '3100']
const COUNTERPARTIES = [
  'Hormigones del Tajo, S.A.',
  'Ferralla Norte, S.L.',
  'Ayuntamiento de Getafe',
  'Grúas Hermanos Ruiz, S.L.',
  'Electroinstalaciones Vega, S.A.',
  'Áridos Montes, S.L.',
  'Diputación de Valladolid',
  'Transportes Lusitania, Lda.',
  'Constructora Andina de México',
  'Servicios Hidráulicos Levante',
  'Señalización Viaria Centro',
  'Kalmora Infraestructuras y Servicios',
]
const OUTCOMES: Record<TaskKey, string[]> = {
  ap: ['POST', 'POST', 'POST', 'HOLD', 'DUPLICATE', 'NOT_INVOICE', 'POST_PAYMENT_BLOCK'],
  ar_billing: ['INVOICE', 'INVOICE', 'SKIP_PENDING_APPROVAL'],
  ar_cash: ['APPLIED', 'APPLIED', 'PARTIAL', 'NON_CUSTOMER'],
  bank_rec: ['MATCHED', 'MATCHED', 'BANK_FEE_NOT_BOOKED', 'UNRECORDED_RECEIPT'],
  ic: ['TIMING', 'DAY_COUNT_BASIS', 'POOLING_NOT_BOOKED'],
  close: ['ACCRUAL', 'PREPAID', 'FX_REVAL', 'BAD_DEBT', 'WIP'],
}
const TASKS: TaskKey[] = ['ap', 'ap', 'ap', 'ap', 'ar_billing', 'ar_cash', 'ar_cash', 'bank_rec', 'bank_rec', 'ic', 'close']
const PROVENANCES: Provenance[] = ['RULE', 'RULE', 'RULE', 'HISTORY', 'MODEL', 'MODEL', 'HUMAN']

function mulberry32(seed: number) {
  let a = seed
  return () => {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function key(task: TaskKey, n: number): string {
  const pad = (v: number, len: number) => String(v).padStart(len, '0')
  switch (task) {
    case 'ap':
      return `API${pad(5000 + n, 6)}`
    case 'ar_billing':
      return `BI-2026-07-${pad(n, 4)}`
    case 'ar_cash':
      return `BL${pad(n, 7)}`
    case 'bank_rec':
      return `ES12-0049-${pad(n % 12, 2)}/BL${pad(n, 7)}`
    case 'ic':
      return `1000-${['1100', '1200', '2100', '3100'][n % 4]}/C${n}`
    case 'close':
      return `ACCRUAL/1100/V${pad(100000 + n, 6)}`
  }
}

export function makeDemoRows(count: number, seed = 7): DemoRow[] {
  const rand = mulberry32(seed)
  const pick = <T,>(list: readonly T[]) => list[Math.floor(rand() * list.length)]
  const rows: DemoRow[] = []
  for (let i = 0; i < count; i++) {
    const task = pick(TASKS)
    const company = pick(COMPANIES)
    const r = rand()
    const status: ItemStatus = r < 0.78 ? 'AUTO' : r < 0.9 ? 'NEEDS_HUMAN' : r < 0.96 ? 'BLOCKED' : 'OPEN'
    const provenance = pick(PROVENANCES)
    const magnitude = Math.pow(10, 3 + rand() * 4.6)
    rows.push({
      id: `${task}:${key(task, i)}`,
      task,
      company,
      counterparty: pick(COUNTERPARTIES),
      amount: Math.round(magnitude) * (task === 'ar_cash' || rand() > 0.08 ? 1 : -1),
      currency: company === '3100' ? 'MXN' : 'EUR',
      date: `2026-07-${String(1 + Math.floor(rand() * 31)).padStart(2, '0')}`,
      status,
      outcome: pick(OUTCOMES[task]),
      provenance,
      confidence: provenance === 'MODEL' || provenance === 'HISTORY' ? Math.round((0.55 + rand() * 0.45) * 100) / 100 : null,
    })
  }
  // A realistic anchor: the certification with ISP and 5 % retention from the plan.
  rows[0] = {
    id: 'ap:API004128',
    task: 'ap',
    company: '1100',
    counterparty: 'Ferralla Norte, S.L.',
    amount: 4202872,
    currency: 'EUR',
    date: '2026-07-31',
    status: 'AUTO',
    outcome: 'POST',
    provenance: 'RULE',
    confidence: 0.97,
  }
  return rows
}
