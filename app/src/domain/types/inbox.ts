// Documents received in the month under `<phase>/inbox/`.

import type { CompanyCode, IsoDate } from './erp'

export type InboxChannel = 'email' | 'facturae' | 'portal' | 'cfdi' | 'paper' | (string & {})

/** `inbox/ap/<doc_id>/message.json` */
export interface InboxMessage {
  doc_id: string
  channel: InboxChannel
  /** ISO local timestamp, e.g. `2026-07-06T14:11:00`. */
  received_at: string
  mailbox: string
  attachments: string[]
  from?: string
  to?: string
  subject?: string
  body?: string
  source?: string
  uploaded_by?: string
}

/** Path of a file relative to the phase root, e.g. `inbox/ap/API004093/factura.pdf`. */
export type DatasetPath = string

export interface ApInboxDoc {
  docId: string
  message: InboxMessage
  /** Paths of the attachments relative to the phase root. */
  files: DatasetPath[]
}

/** `inbox/ar/billing/<item>/meta json` + its documents. */
export interface BillingItemMeta {
  billing_item: string
  type: string
  company: CompanyCode
  contract: string
  customer: string
  month: string
  documents: string[]
  [k: string]: unknown
}

export interface ArBillingInboxItem {
  item: string
  meta: BillingItemMeta | null
  files: DatasetPath[]
}

export interface ArInbox {
  billing: ArBillingInboxItem[]
  /** FACe exports (CSV) and customer payment advices (JSON + PDF). */
  remittances: DatasetPath[]
  /** Penalty notices received in the month (PDF). */
  notices: DatasetPath[]
}

export interface FileEntry {
  path: DatasetPath
  size: number
  lastModified?: IsoDate
}
