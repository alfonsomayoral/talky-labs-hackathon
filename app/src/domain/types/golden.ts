// `<phase>/golden/` — only in the dev phase. Same shapes as the deliverables plus
// internal fields (`cases`, `je`, `estimate`, …) that must be stripped before
// treating golden as a run.

import type { Cents, CompanyCode } from './erp'
import type { Deliverables } from './deliverables'

export interface TrialBalanceRow {
  company: CompanyCode
  account: string
  balance: Cents
}

export interface GoldenSummary {
  phase: string
  month: string
  ap_documents: number
  ar_billing_items: number
  ar_receipts: number
  bank_accounts: number
  ic_differences: number
  close_entries: number
  tagged: Record<string, number>
}

export interface Golden {
  deliverables: Deliverables
  trialBalanceTruth: TrialBalanceRow[]
  trialBalanceRecorded: TrialBalanceRow[]
  summary: GoldenSummary | null
}

/**
 * Generator hints present in golden rows that a real agent could not know. They are
 * stripped when golden is opened as a run; every other field is kept (the scorer
 * ignores extra fields, and some — `company`, `currency` — are legitimately used).
 */
export const GOLDEN_INTERNAL_FIELDS: Record<keyof Deliverables, readonly string[]> = {
  ap: ['cases'],
  ar_billing: [],
  ar_cash: [],
  bank_rec: [],
  ic: ['note'],
  close: ['je', 'estimate'],
}
