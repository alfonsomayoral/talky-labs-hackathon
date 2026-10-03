// ERP snapshot files under `<phase>/erp/`. Amounts are integer cents in the
// company's local currency; quantities are thousandths (`quantity_milli`).

export type CompanyCode = '1000' | '1100' | '1200' | '1300' | '1910' | '2100' | '3100' | (string & {})
export type Cents = number
export type IsoDate = string

export interface Company {
  code: CompanyCode
  name: string
  short: string
  country: string
  currency: string
  role: string
  city: string
  street: string
  postal_code: string
  tax_id: string
  vat_id: string
  partners: string[][] | null
}

export interface ChartAccount {
  account: string
  description: string
  type: string
  open_items: boolean
}

export interface TaxCode {
  country: string
  kind: string
  rate: number
  desc: string
}

export interface WithholdingCode {
  rate: number
  account: string
  desc: string
  model: string
}

export interface CustomerDeduction {
  rate: number
  account: string
  desc: string
}

export interface TaxCodes {
  tax_codes: Record<string, TaxCode>
  withholdings: Record<string, WithholdingCode>
  customer_deductions: Record<string, CustomerDeduction>
}

export interface CostCenter {
  id: string
  company: CompanyCode
  desc: string
}

export interface Project {
  id: string
  company: CompanyCode
  name: string
  town: string
  kind: string
  public_works: boolean
  start: IsoDate
  planned_end: IsoDate
  budget_cost: Cents
  wbs: { id: string; desc: string; sub: string }[]
}

export interface Address {
  street: string
  postal_code?: string
  city: string
  region?: string
  country?: string
}

export interface Vendor {
  id: string
  name: string
  tax_id: string
  vat_id: string
  country: string
  currency: string
  language: string
  address: Address
  email: string
  natural_person: boolean
  archetype: string
  reconciliation_account: string
  default_tax_code: string
  default_gl_account: string
  withholding: string | null
  payment_method: string
  payment_terms_days: number
  bank: { iban: string | null; clabe?: string; account?: string; swift?: string }
  bank_history: { iban: string; valid_to: IsoDate }[]
  companies: CompanyCode[]
  po_required: boolean
  created_on: IsoDate
  intercompany: CompanyCode | null
  guarantee_retention_bp?: number
  alternative_payee?: { type: string; name: string; iban: string; from_date: IsoDate }
  garnishments?: { ref: string; amount: Cents; from_date: IsoDate }[]
}

export interface ContractorCertificate {
  vendor: string
  issued_on: IsoDate
  valid_until: IsoDate
  reference: string
}

export interface Dir3 {
  oficina_contable: string
  organo_gestor: string
  unidad_tramitadora: string
}

export interface Customer {
  id: string
  name: string
  tax_id: string
  country: string
  kind: string
  address: Address
  currency: string
  iban: string | null
  dir3?: Dir3
  insolvency?: { declared_on: IsoDate; court: string; proceeding: string }
  mandate?: string
  group?: CompanyCode
}

export interface SalesContract {
  id: string
  company: CompanyCode
  customer: string
  kind: string
  name?: string
  project?: string
  value?: Cents
  tax: string
  retention_bp?: number
  terms_days: number
  start: IsoDate
  end?: IsoDate
  factoring?: boolean
  mx5mill?: boolean
  advance_bp?: number
  cc?: string
  fee?: Cents
  price_revision?: boolean
  penalty_prob?: number
  plants?: string[]
  share_bp?: number
  price_mwh?: number
}

export interface PurchaseOrderItem {
  item: number
  material: string
  description: string
  uom: string
  quantity_milli: number
  unit_price: Cents
  gl_account: string
  wbs: string | null
  cost_center: string | null
  tax_code: string
  asset: string | null
}

export interface PurchaseOrder {
  id: string
  company: CompanyCode
  vendor: string
  created_on: IsoDate
  type: string
  currency: string
  project: string | null
  purchasing_group: string
  requester: string
  text: string
  items: PurchaseOrderItem[]
}

export interface GoodsReceipt {
  id: string
  type: string
  company: CompanyCode
  po: string
  po_item: number
  vendor: string
  posting_date: IsoDate
  quantity_milli: number
  amount: Cents
  reference: string
  journal_entry: string
}

export interface JournalLine {
  line: number
  account: string
  debit: Cents
  credit: Cents
  currency: string
  amount_doc: number
  partner: string | null
  cost_center: string | null
  wbs: string | null
  tax_code: string | null
  assignment: string | null
  text: string
}

export interface JournalEntry {
  id: string
  company: CompanyCode
  doc_type: string
  posting_date: IsoDate
  document_date: IsoDate
  reference: string
  header_text: string
  /** Origin of the entry (AP, SD, MM, F110, POOL, CLOSE_ACCRUAL, …). */
  source: string
  currency: string
  lines: JournalLine[]
}

/** `<journal entry id>#<line number>` — the book line id used by bank reconciliation. */
export type BookLineId = string

export interface OpenItem {
  company: CompanyCode
  account: string
  partner: string
  assignment: string
  balance: Cents
}

export interface ApInvoice {
  doc_id: string
  company: CompanyCode
  vendor: string
  kind: string
  number: string
  issue_date: IsoDate
  received_on: IsoDate
  posted_on: IsoDate
  journal_entry: string
  currency: string
  net: Cents
  tax: Cents
  gross: Cents
  withholding: Cents
  retention: Cents
  payable: Cents
  due_date: IsoDate
  po_refs: string[]
  decision: string
  payee: { type: string } | null
  cases?: string[]
}

export interface ApDocumentLogEntry {
  doc_id: string
  received_on: IsoDate
  kind: string
  vendor: string
  company: CompanyCode
  number: string | null
  decision: string
  reasons: string[]
  duplicate_of: string | null
  corrected_by: string | null
  journal_entry: string | null
  resolved_on: IsoDate | null
}

export interface ArInvoice {
  id: string
  company: CompanyCode
  customer: string
  contract: string
  kind: string
  date: IsoDate
  due_date: IsoDate
  tax_code: string
  net: Cents
  tax: Cents
  gross: Cents
  retention: Cents
  deductions: { code: string; amount: Cents; account: string }[]
  payable: Cents
  currency: string
  factored: boolean
  journal_entry: string
  face: (Dir3 & { registry?: string }) | null
  certification: string | null
}

/** Billing history is heterogeneous by `type` (certification, municipal fee, PPA, market, revision). */
export interface BillingHistoryEntry {
  id: string
  type: string
  company: CompanyCode
  contract: string
  customer: string
  month: string
  cert?: {
    id: string
    contract: string
    project: string
    number: number
    month: string
    cumulative: Cents
    previous: Cents
    current: Cents
    approved: boolean
    approved_on: IsoDate | null
    approver: string
    lines: { desc: string; [k: string]: unknown }[]
  }
  fee?: Cents
  extra_services?: { order: string; desc: string; amount: Cents; approved: boolean }[]
  production?: { period: string; plants: { plant: string; name: string; mwh_milli: number }[]; share_bp: number; price_eur_mwh: number }
  settlement?: { period: string; plants: { plant: string; name: string; mwh_milli: number; amount: Cents }[]; avg_price: number; deviations: Cents }
  revision?: { old_fee: Cents; new_fee: Cents; effective: IsoDate; approved_on: IsoDate; months: string[]; decree: string }
}

export interface PromissoryNote {
  number: string
  customer: string
  company: CompanyCode
  received_on: IsoDate
  maturity: IsoDate
  amount: Cents
  bank: string
  applications: { invoice: string; amount: Cents }[]
  journal_entry: string
}

export interface FactoringAssignment {
  invoice: string
  remittance: string
  date: IsoDate
  advance: Cents
  interest: Cents
  fee: Cents
  customer: string
}

export interface SepaRemittance {
  id: string
  date: IsoDate
  invoices: string[]
  total: Cents
}

export interface PenaltyNotice {
  invoice: string
  contract: string
  customer: string
  amount: Cents
  notified_on: IsoDate
  resolution: string
}

export interface IntercompanyAgreements {
  management_fees: Record<string, { monthly_eur_2025: Cents; monthly_eur_2026: Cents; issuer: CompanyCode; basis: string }>
  loan: { id: string; principal: Cents; rate_bp: number; basis: string; start: IsoDate; lender: CompanyCode; borrower: CompanyCode; note: string }
  cash_pooling: { header: CompanyCode; participants: CompanyCode[]; scheme: string; interest: string }
  ute: Record<string, unknown>
}

export interface FxRate {
  date: IsoDate
  base: string
  currency: string
  rate: number
  source: string
}

export interface BankAccount {
  id: string
  company: CompanyCode
  bank: string
  bic: string
  iban: string | null
  clabe: string | null
  gl_account: string
  currency: string
  statement_format: string
  roles: string[]
}
