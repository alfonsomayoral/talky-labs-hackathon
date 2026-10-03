// Pure helpers behind /datos: journal filters in the URL, cross-links between masters and items, file kinds.

import type { DatasetCore, EvidenceRef, ItemId, JournalQuery, WorkItem } from '@/domain/types'

// ---------------------------------------------------------------- routes

export const dataPath = {
  vendor: (id: string) => `/datos/proveedores/${encodeURIComponent(id)}`,
  customer: (id: string) => `/datos/clientes/${encodeURIComponent(id)}`,
  account: (account: string) => `/datos/cuentas/${encodeURIComponent(account)}`,
  project: (id: string) => `/datos/proyectos/${encodeURIComponent(id)}`,
  entry: (id: string) => `/datos/diario/${encodeURIComponent(id)}`,
  journal: (q: JournalFilters) => {
    const params = journalParams(q).toString()
    return params ? `/datos/diario?${params}` : '/datos/diario'
  },
  document: (id: string) => `/datos/documentos/${encodeURIComponent(id)}`,
  file: (path: string) => `/datos/documentos/fichero?path=${encodeURIComponent(path)}`,
  statement: (account: string, month: string) => `/datos/extractos/${encodeURIComponent(account)}/${month}`,
}

// ---------------------------------------------------------------- journal filters <-> URL

export type JournalFilters = Pick<JournalQuery, 'company' | 'account' | 'source' | 'from' | 'to' | 'text'>

const FILTER_KEYS = ['company', 'account', 'source', 'from', 'to', 'text'] as const satisfies readonly (keyof JournalFilters)[]
const PARAM: Record<(typeof FILTER_KEYS)[number], string> = { company: 'sociedad', account: 'cuenta', source: 'origen', from: 'desde', to: 'hasta', text: 'q' }

export function journalFilters(params: URLSearchParams): JournalFilters {
  const out: JournalFilters = {}
  for (const k of FILTER_KEYS) {
    const v = params.get(PARAM[k])?.trim()
    if (v) out[k] = v
  }
  return out
}

export function journalParams(filters: JournalFilters): URLSearchParams {
  const params = new URLSearchParams()
  for (const k of FILTER_KEYS) {
    const v = filters[k]?.trim()
    if (v) params.set(PARAM[k], v)
  }
  return params
}

// ---------------------------------------------------------------- cross-links

const refersTo = (e: EvidenceRef, file: string, key: string) => e.kind === 'erp' && e.file === file && e.key === key

/** Items of the active run whose evidence cites this master record. */
export function itemsCiting(items: WorkItem[], file: string, key: string): WorkItem[] {
  return items.filter((it) => it.evidence.some((e) => refersTo(e, file, key)))
}

/** Items whose evidence cites a line of this journal entry (`<id>#<line>`). */
export function itemsCitingEntry(items: WorkItem[], entryId: string): WorkItem[] {
  const prefix = `${entryId}#`
  return items.filter((it) => it.evidence.some((e) => e.kind === 'journal' && (e.book_line === entryId || e.book_line.startsWith(prefix))))
}

export function vendorLinks(core: DatasetCore, vendorId: string) {
  return {
    invoices: core.apInvoices.filter((i) => i.vendor === vendorId).sort((a, b) => b.issue_date.localeCompare(a.issue_date)),
    documentLog: core.apDocumentLog.filter((d) => d.vendor === vendorId).sort((a, b) => b.received_on.localeCompare(a.received_on)),
    purchaseOrders: core.purchaseOrders.filter((p) => p.vendor === vendorId).sort((a, b) => b.created_on.localeCompare(a.created_on)),
    certificates: core.contractorCertificates.filter((c) => c.vendor === vendorId),
  }
}

export function customerLinks(core: DatasetCore, customerId: string) {
  return {
    contracts: core.salesContracts.filter((c) => c.customer === customerId),
    invoices: core.arInvoices.filter((i) => i.customer === customerId).sort((a, b) => b.date.localeCompare(a.date)),
    openItems: core.openItems.filter((o) => o.partner === customerId),
    promissoryNotes: core.promissoryNotes.filter((p) => p.customer === customerId),
  }
}

/** Where a partner id on a journal line points: vendor, customer or nothing known. */
export function partnerPath(core: DatasetCore, partner: string | null): string | null {
  if (!partner) return null
  if (core.vendors.some((v) => v.id === partner)) return dataPath.vendor(partner)
  if (core.customers.some((c) => c.id === partner)) return dataPath.customer(partner)
  return null
}

/** Items of the run that a bank statement line feeds (cash application and bank reconciliation). */
export function bankLineItems(itemsById: ReadonlyMap<ItemId, WorkItem> | null, account: string, bankLine: string): WorkItem[] {
  if (!itemsById) return []
  return [`ar_cash:${bankLine}`, `bank_rec:${account}/${bankLine}`].flatMap((id) => itemsById.get(id) ?? [])
}

// ---------------------------------------------------------------- files

export type FileKind = 'pdf' | 'xml' | 'json' | 'text' | 'other'

export function fileKind(path: string): FileKind {
  const ext = path.slice(path.lastIndexOf('.') + 1).toLowerCase()
  if (ext === 'pdf') return 'pdf'
  if (ext === 'xml') return 'xml'
  if (ext === 'json' || ext === 'jsonl') return 'json'
  if (ext === 'csv' || ext === 'txt' || ext === 'n43') return 'text'
  return 'other'
}

export const fileName = (path: string) => path.slice(path.lastIndexOf('/') + 1)

/** Indents XML two spaces per level; text-only elements stay on one line. Malformed input comes back as is. */
export function prettyXml(xml: string): string {
  const tokens = xml.replace(/>\s+</g, '><').trim().match(/<[^>]+>|[^<]+/g)
  if (!tokens) return xml
  const out: string[] = []
  let depth = 0
  for (let i = 0; i < tokens.length; i++) {
    const t = tokens[i]
    const pad = '  '.repeat(Math.max(0, depth))
    if (t.startsWith('</')) {
      depth--
      out.push('  '.repeat(Math.max(0, depth)) + t)
    } else if (t.startsWith('<?') || t.startsWith('<!') || t.endsWith('/>')) out.push(pad + t)
    else if (t.startsWith('<')) {
      const text = tokens[i + 1]
      const close = tokens[i + 2]
      if (text !== undefined && !text.startsWith('<') && close?.startsWith('</')) {
        out.push(pad + t + text + close)
        i += 2
      } else {
        out.push(pad + t)
        depth++
      }
    } else out.push(pad + t.trim())
  }
  return depth === 0 ? out.join('\n') : xml
}

export function prettyJson(text: string): string {
  try {
    return JSON.stringify(JSON.parse(text), null, 2)
  } catch {
    return text
  }
}
