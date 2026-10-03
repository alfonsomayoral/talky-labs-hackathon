// Engine-derived view model: one WorkItem per unit of work the agent resolved.

import type { Cents, CompanyCode } from './erp'
import type { TaskKey } from './deliverables'
import type { EvidenceRef } from './bundle'

export type ItemStatus = 'AUTO' | 'NEEDS_HUMAN' | 'BLOCKED' | 'OPEN'
export type Provenance = 'RULE' | 'HISTORY' | 'MODEL' | 'HUMAN' | 'REFERENCE'

/**
 * Item ids:
 *   ap:<doc_id> · ar_billing:<billing_item> · ar_cash:<bank_line>
 *   bank_rec:<account>/<bank_line|book_line|match-n> · ic:<c1>-<c2>/<cause>
 *   close:<type>/<company>/<key>
 */
export type ItemId = string

export interface WorkItem {
  id: ItemId
  task: TaskKey
  key: string
  company: CompanyCode | null
  title: string
  counterparty: string | null
  amount: Cents | null
  currency: string | null
  date: string | null
  status: ItemStatus
  /** Decision / category / type, e.g. POST, BANK_FEE_NOT_BOOKED, ACCRUAL. */
  outcome: string
  reasons: string[]
  confidence: number | null
  provenance: Provenance
  policyRefs: string[]
  evidence: EvidenceRef[]
  /** Net effect on the trial balance (sum of debits of its entries), 0 when none. */
  tbImpact: Cents
  /** Index of the row in the deliverable file (for bank_rec: the account row). */
  rowIndex: number
}
