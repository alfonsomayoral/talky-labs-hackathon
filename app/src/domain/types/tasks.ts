// `<phase>/tasks/*.json` — the exact list of what must be solved.

import type { CompanyCode } from './erp'

export interface Tasks {
  /** tasks/ap_documents.json */
  ap_documents: string[]
  /** tasks/ar_billing_items.json */
  ar_billing_items: string[]
  /** tasks/ar_receipts.json — bank_line ids */
  ar_receipts: string[]
  /** tasks/bank_accounts.json */
  bank_accounts: string[]
  /** tasks/intercompany.json */
  intercompany: { pairs: [CompanyCode, CompanyCode][]; accounts: string[] }
  /** tasks/close.json */
  close: { month: string; steps: string[] }
}
