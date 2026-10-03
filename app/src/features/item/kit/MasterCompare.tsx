import clsx from 'clsx'
import { Check, Minus, X } from 'lucide-react'
import type { ApRow, Company, EInvoiceSummary, InboxMessage, Vendor } from '@/domain/types'
import { useDatasetStore } from '@/data/stores'
import { Mono } from '@/components'
import { formatDate } from '@/lib/format'
import { fileExtension } from './evidence'
import { useAsync } from './useAsync'
import styles from './MasterCompare.module.css'

export interface CompareRow {
  label: string
  /** Value read from the document (null when the document does not say). */
  document: string | null
  /** Value in the master data (null when there is no master record). */
  master: string | null
  mono?: boolean
  /** Extra context under the row (e.g. a registered factoring assignment). */
  note?: string
}

export type CompareState = 'equal' | 'different' | 'unknown'

const norm = (s: string) =>
  s
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9@.]/g, '')

export function compareState(row: CompareRow): CompareState {
  if (row.document === null || row.master === null) return 'unknown'
  return norm(row.document) === norm(row.master) ? 'equal' : 'different'
}

export interface MasterCompareProps {
  rows: CompareRow[]
  title?: string
  /** Line under the table (e.g. which values could not be read from the document). */
  note?: string
  className?: string
}

/** Document vs master data, field by field: ✓ equal, ✗ different (highlighted), – unknown. */
export function MasterCompare({ rows, title = 'Documento frente a la ficha', note, className }: MasterCompareProps) {
  return (
    <div className={clsx(styles.compare, className)}>
      <table className={styles.table}>
        <caption className={styles.caption}>{title}</caption>
        <thead>
          <tr>
            <th aria-label="Resultado" />
            <th>Campo</th>
            <th>Documento</th>
            <th>Ficha</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const state = compareState(r)
            const Icon = state === 'equal' ? Check : state === 'different' ? X : Minus
            return (
              <tr key={r.label} data-state={state}>
                <td className={styles.state}>
                  <Icon aria-label={state === 'equal' ? 'Coincide' : state === 'different' ? 'No coincide' : 'Sin dato'} />
                </td>
                <td className={styles.label}>{r.label}</td>
                <td>{cell(r.document, r.mono)}</td>
                <td>
                  {cell(r.master, r.mono)}
                  {r.note && <span className={styles.note}>{r.note}</span>}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {note && <p className={styles.footnote}>{note}</p>}
    </div>
  )
}

const cell = (v: string | null, mono?: boolean) => (v === null ? <span className={styles.none}>—</span> : mono ? <Mono>{v}</Mono> : v)

const domainOf = (email: string | null | undefined) => (email && email.includes('@') ? email.split('@').pop()!.trim().toLowerCase() : null)

export interface ApMasterInput {
  row: Partial<ApRow>
  vendor: Vendor | null
  company: Company | null
  message: InboxMessage | null
  einvoice: EInvoiceSummary | null
}

/** Rows for an AP document: issuer, NIF, IBAN, sender domain and addressee against the masters. */
export function apMasterRows({ row, vendor, company, message, einvoice }: ApMasterInput): CompareRow[] {
  const rows: CompareRow[] = [
    { label: 'Proveedor', document: einvoice?.seller.name ?? null, master: vendor?.name ?? (row.vendor_id ? null : 'Sin alta en el maestro') },
    { label: 'NIF del emisor', document: einvoice?.seller.taxId ?? null, master: vendor?.tax_id ?? null, mono: true },
  ]
  const payee = vendor?.alternative_payee
  rows.push({
    label: 'IBAN',
    document: einvoice?.iban ?? null,
    master: vendor ? (vendor.bank?.iban ?? null) : null,
    mono: true,
    note: payee ? `Cesión registrada a ${payee.name} (${payee.iban}) desde ${formatDate(payee.from_date)}` : vendor?.bank_history?.length ? `Anteriores: ${vendor.bank_history.map((h) => h.iban).join(', ')}` : undefined,
  })
  if (message?.from) rows.push({ label: 'Dominio del remitente', document: domainOf(message.from), master: domainOf(vendor?.email), mono: true })
  if (einvoice?.buyer.taxId || company) rows.push({ label: 'NIF del destinatario', document: einvoice?.buyer.taxId ?? null, master: company?.tax_id ?? null, mono: true })
  return rows
}

/** MasterCompare of an AP document, reading its message.json and e-invoice XML (when there is one). */
export function ApMasterCompare({ row, className }: { row: Partial<ApRow>; className?: string }) {
  const api = useDatasetStore((s) => s.api)
  const docId = String(row.doc_id ?? '')
  const state = useAsync(async () => {
    if (!api) return null
    const inbox = api.core.apInbox.find((d) => d.docId === docId)
    const xml = inbox?.files.find((f) => fileExtension(f) === 'xml')
    const einvoice = xml && api.einvoice ? await api.einvoice(xml).catch(() => null) : null
    return { message: inbox?.message ?? null, einvoice }
  }, [api, docId])
  if (!api || state.status !== 'ready' || !state.data) return null
  const vendor = row.vendor_id ? (api.core.vendors.find((v) => v.id === row.vendor_id) ?? null) : null
  const company = row.company ? (api.core.companies.find((c) => c.code === row.company) ?? null) : null
  const { message, einvoice } = state.data
  // Without an e-invoice only the sender and the master IBAN are known: hide rows that cannot compare.
  const rows = apMasterRows({ row, vendor, company, message, einvoice }).filter((r) => einvoice || r.document !== null || r.label === 'IBAN')
  const note = einvoice ? undefined : 'El documento es un PDF: el emisor, el NIF y el IBAN se comprueban sobre el documento en Evidencia.'
  return <MasterCompare className={className} rows={rows} note={note} />
}
