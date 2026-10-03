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

/** Key fields of a Facturae 3.2.x or CFDI 4.0 XML, for evidence display (amounts in cents). */
export interface EInvoiceSummary {
  format: 'facturae' | 'cfdi'
  version: string | null
  invoiceNumber: string | null
  series: string | null
  issueDate: IsoDate | null
  period: { start: IsoDate | null; end: IsoDate | null } | null
  currency: string | null
  seller: { taxId: string | null; name: string | null }
  buyer: { taxId: string | null; name: string | null }
  /** Taxable base (Facturae TotalGrossAmountBeforeTaxes, CFDI SubTotal − Descuento). */
  net: number | null
  tax: number | null
  /** Taxes withheld (IRPF / ISR-IVA retenidos). */
  withheld: number | null
  /** Invoice total (Facturae InvoiceTotal, CFDI Total). */
  total: number | null
  /** Facturae AmountsWithheld (guarantee retention), when present. */
  retention: number | null
  /** Amount to pay (Facturae TotalExecutableAmount). */
  payable: number | null
  taxes: { type: string | null; rate: number | null; base: number | null; amount: number | null; withheld: boolean }[]
  lines: { description: string; quantity: number | null; unitPrice: number | null; amount: number | null; reference: string | null }[]
  iban: string | null
  /** Facturae `Corrective` block (credit notes / rectificativas). */
  corrects: { invoiceNumber: string | null; reason: string | null } | null
  /** CFDI: TipoDeComprobante (I, E, P…), MetodoPago, UUID of the fiscal stamp. */
  cfdi: { type: string | null; paymentMethod: string | null; uuid: string | null; related: string[] } | null
  notes: string[]
}
