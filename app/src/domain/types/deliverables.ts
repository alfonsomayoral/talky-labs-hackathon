// The six official deliverables (FORMATO_ENTREGA.md). One JSONL file each.

import type { Cents, CompanyCode, IsoDate } from './erp'

export const TASK_KEYS = ['ap', 'ar_billing', 'ar_cash', 'bank_rec', 'ic', 'close'] as const
export type TaskKey = (typeof TASK_KEYS)[number]

export const TASK_WEIGHTS: Record<TaskKey | 'trial_balance', number> = {
  ap: 0.3,
  ar_billing: 0.1,
  ar_cash: 0.15,
  bank_rec: 0.2,
  ic: 0.05,
  close: 0.1,
  trial_balance: 0.1,
}

/** A journal entry line as delivered. Lines may carry their own `company` (ar_cash, ic, bank adjustments). */
export interface JeLine {
  company?: CompanyCode
  account: string
  debit: Cents
  credit: Cents
  partner?: string | null
  cost_center?: string | null
  wbs?: string | null
  assignment?: string | null
  [k: string]: unknown
}

export interface JournalEntryOut {
  company: CompanyCode
  lines: JeLine[]
  [k: string]: unknown
}

// ---------------------------------------------------------------- AP
export const AP_DOCUMENT_TYPES = [
  'INVOICE',
  'CREDIT_NOTE',
  'DOWN_PAYMENT_REQUEST',
  'PROFORMA',
  'VENDOR_STATEMENT',
  'FACTORING_NOTICE',
  'TAX_GARNISHMENT_ORDER',
  'BANK_DETAILS_CHANGE',
  'CONTRACTOR_TAX_CERTIFICATE',
] as const
export type ApDocumentType = (typeof AP_DOCUMENT_TYPES)[number]

export const AP_DECISIONS = ['POST', 'POST_PAYMENT_BLOCK', 'HOLD', 'REJECT', 'DUPLICATE', 'NOT_INVOICE'] as const
export type ApDecision = (typeof AP_DECISIONS)[number]

export const AP_REASONS = [
  'DUPLICATE',
  'MANDATORY_FIELD_MISSING',
  'WRONG_ADDRESSEE',
  'ISP_NOT_APPLIED',
  'VAT_RATE_INCORRECT',
  'WITHHOLDING_MISSING',
  'ARITHMETIC_ERROR',
  'CERTIFICATION_CUMULATIVE_BILLED',
  'CFDI_MISMATCH',
  'VENDOR_NOT_IN_MASTER',
  'BANK_DETAILS_CHANGED',
  'QTY_NOT_RECEIVED',
  'PRICE_VARIANCE',
  'CONTRACTOR_CERTIFICATE_EXPIRED',
] as const
export type ApReason = (typeof AP_REASONS)[number]

export const AP_ACTIONS = [
  'NONE',
  'REGISTER_ALTERNATIVE_PAYEE',
  'REGISTER_EMBARGO',
  'UPDATE_BANK_DETAILS',
  'UPDATE_CONTRACTOR_CERTIFICATE',
] as const
export type ApAction = (typeof AP_ACTIONS)[number]

export interface ApLine {
  amount: Cents
  account: string
  cost_center: string | null
  wbs: string | null
  tax_code: string
  po?: string | null
  po_item?: number | null
  [k: string]: unknown
}

export interface ApRow {
  doc_id: string
  document_type: ApDocumentType
  decision: ApDecision
  reasons: string[]
  company: CompanyCode | null
  vendor_id: string | null
  invoice_number: string | null
  invoice_date: IsoDate | null
  currency: string | null
  net: Cents | null
  tax: Cents | null
  gross: Cents | null
  withholding: Cents | null
  retention: Cents | null
  payable: Cents | null
  duplicate_of: string | null
  payee: { type: 'FACTOR' | 'AEAT_EMBARGO' } | null
  payment_block: 'CONTRACTOR_CERTIFICATE_EXPIRED' | null
  action: ApAction | null
  lines: ApLine[]
  journal_entry: JournalEntryOut | null
  [k: string]: unknown
}

// ---------------------------------------------------------------- AR billing
export interface ArBillingLine {
  description: string
  amount: Cents
  account: string
  wbs?: string | null
  cost_center?: string | null
  [k: string]: unknown
}

export interface ArBillingInvoice {
  date: IsoDate
  due_date: IsoDate
  tax_code: string
  net: Cents
  tax: Cents
  retention: Cents
  deductions: { code?: string; amount: Cents; account?: string; [k: string]: unknown }[]
  payable: Cents
  face?: { oficina_contable: string; organo_gestor: string; unidad_tramitadora: string } | null
  lines: ArBillingLine[]
  [k: string]: unknown
}

export interface ArBillingRow {
  billing_item: string
  expected: 'INVOICE' | 'SKIP_PENDING_APPROVAL'
  invoice?: ArBillingInvoice | null
  journal_entry?: JournalEntryOut | null
  [k: string]: unknown
}

// ---------------------------------------------------------------- AR cash
export const AR_RESIDUAL_TYPES = ['PENALTY', 'NETTING_AP', 'OVERPAYMENT_DUPLICATE', 'FACTORED_MISDIRECTED', 'NON_CUSTOMER'] as const
export type ArResidualType = (typeof AR_RESIDUAL_TYPES)[number]

export interface ArCashApplication {
  invoice?: string
  pagare?: string
  amount: Cents
}

export interface ArCashResidual {
  type: ArResidualType
  invoice?: string
  amount: Cents
  account?: string
  [k: string]: unknown
}

export interface ArCashRow {
  bank_line: string
  customer: string | null
  applications: ArCashApplication[]
  residuals: ArCashResidual[]
  adjustment: JeLine[]
  [k: string]: unknown
}

// ---------------------------------------------------------------- Bank reconciliation
export const BANK_CATEGORIES = [
  'BANK_FEE_NOT_BOOKED',
  'INTEREST_NOT_BOOKED',
  'LOAN_INTEREST_NOT_BOOKED',
  'CARD_SETTLEMENT_NOT_BOOKED',
  'DIRECT_DEBIT_NOT_BOOKED',
  'RETURNED_DIRECT_DEBIT',
  'FX_RATE_DIFFERENCE',
  'FACTORING_CHARGES_NOT_BOOKED',
  'POOLING_NOT_BOOKED',
  'UNRECORDED_RECEIPT',
  'BOOK_AMOUNT_ERROR',
  'WRONG_BANK_ACCOUNT',
  'BOOK_DUPLICATE',
  'BANK_ERROR',
  'OUTSTANDING_PAYMENT',
  'TRANSFER_IN_TRANSIT',
  'PRIOR_PERIOD_BANK_ITEM',
  'FX_REVALUATION',
] as const
export type BankCategory = (typeof BANK_CATEGORIES)[number]

export interface BankMatch {
  bank_lines: string[]
  book_lines: string[]
  category?: string
  [k: string]: unknown
}

export interface BankRecRow {
  account: string
  company: CompanyCode
  matches: BankMatch[]
  unmatched_bank: { bank_line: string; category: BankCategory | string }[]
  unmatched_book: { book_line: string; category: BankCategory | string }[]
  adjustments: { category: BankCategory | string; lines: JeLine[] }[]
  [k: string]: unknown
}

// ---------------------------------------------------------------- Intercompany
export const IC_CAUSES = ['INVOICE_IN_TRANSIT', 'INTEREST_DAY_COUNT', 'WRONG_TRADING_PARTNER', 'DUPLICATE_POSTING', 'POOLING_NOT_BOOKED'] as const
export type IcCause = (typeof IC_CAUSES)[number]

export interface IcRow {
  pair: [CompanyCode, CompanyCode]
  cause: IcCause | string
  amount?: Cents
  responsible?: CompanyCode
  adjustment: JeLine[]
  [k: string]: unknown
}

// ---------------------------------------------------------------- Close
export const CLOSE_TYPES = ['ACCRUAL', 'PREPAID', 'WIP_REVENUE', 'FX_REVAL', 'BAD_DEBT', 'DOUBTFUL_RECLASS'] as const
export type CloseType = (typeof CLOSE_TYPES)[number]

export interface CloseRow {
  type: CloseType | string
  company: CompanyCode
  vendor?: string
  invoice?: string
  item?: string
  customer?: string
  billing_item?: string
  amount: Cents
  journal_entry?: JournalEntryOut | null
  [k: string]: unknown
}

// ---------------------------------------------------------------- Bundle of the six
export interface Deliverables {
  ap: ApRow[]
  ar_billing: ArBillingRow[]
  ar_cash: ArCashRow[]
  bank_rec: BankRecRow[]
  ic: IcRow[]
  close: CloseRow[]
}

export const DELIVERABLE_FILES: Record<TaskKey, string> = {
  ap: 'ap.jsonl',
  ar_billing: 'ar_billing.jsonl',
  ar_cash: 'ar_cash.jsonl',
  bank_rec: 'bank_rec.jsonl',
  ic: 'ic.jsonl',
  close: 'close.jsonl',
}
