import { useEffect, useMemo, useState } from 'react'
import clsx from 'clsx'
import { ExternalLink, FileQuestion, Mail, Paperclip } from 'lucide-react'
import type { EInvoiceSummary, InboxMessage } from '@/domain/types'
import { useDatasetStore } from '@/data/stores'
import { Amount, EmptyState, KeyValue, Mono, Skeleton } from '@/components'
import { formatDate, formatDateTime } from '@/lib/format'
import { fileExtension } from './evidence'
import { JsonView } from './JsonView'
import { useAsync } from './useAsync'
import styles from './DocumentViewer.module.css'

export interface DocumentViewerProps {
  /** Path inside the dataset, e.g. `inbox/ap/API004128/factura_2026-001968.pdf`. */
  path: string
  /** PDF/image height in px. */
  height?: number
  className?: string
}

type Loaded = { kind: 'pdf' | 'image'; blob: Blob } | { kind: 'xml'; text: string; einvoice: EInvoiceSummary | null } | { kind: 'json'; value: unknown; text: string } | { kind: 'text'; text: string }

const MAX_TEXT = 400_000

/** Any inbox/bank file: PDF in an iframe (blob URL), XML pretty-printed with its e-invoice summary, JSON, email header, text. */
export function DocumentViewer({ path, height = 560, className }: DocumentViewerProps) {
  const api = useDatasetStore((s) => s.api)
  const state = useAsync(async (): Promise<Loaded> => {
    if (!api) throw new Error('No hay dataset cargado')
    const ext = fileExtension(path)
    const blob = await api.readFile(path)
    if (ext === 'pdf') return { kind: 'pdf', blob }
    if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) return { kind: 'image', blob }
    const text = await blob.text()
    if (ext === 'xml') return { kind: 'xml', text, einvoice: api.einvoice ? await api.einvoice(path).catch(() => null) : null }
    if (ext === 'json') {
      try {
        return { kind: 'json', value: JSON.parse(text), text }
      } catch {
        return { kind: 'text', text }
      }
    }
    return { kind: 'text', text }
  }, [api, path])

  if (state.status === 'loading') return <Skeleton height={height > 200 ? 160 : height} />
  if (state.status === 'error') return <EmptyState size="sm" icon={<FileQuestion />} title="No se pudo abrir el fichero" description={state.error} />
  const doc = state.data
  return (
    <div className={clsx(styles.viewer, className)}>
      {(doc.kind === 'pdf' || doc.kind === 'image') && <BlobView blob={doc.blob} kind={doc.kind} path={path} height={height} />}
      {doc.kind === 'xml' && <XmlView text={doc.text} einvoice={doc.einvoice} />}
      {doc.kind === 'json' && (path.endsWith('message.json') && isMessage(doc.value) ? <EmailView message={doc.value} /> : <JsonView value={doc.value} depth={2} />)}
      {doc.kind === 'text' && <pre className={styles.pre}>{doc.text.slice(0, MAX_TEXT)}</pre>}
    </div>
  )
}

const isMessage = (v: unknown): v is InboxMessage => !!v && typeof v === 'object' && 'channel' in v && 'attachments' in v

function useObjectUrl(blob: Blob, type: string | null): string | null {
  const [url, setUrl] = useState<string | null>(null)
  useEffect(() => {
    if (typeof URL.createObjectURL !== 'function') return
    const typed = type && blob.type !== type ? new Blob([blob], { type }) : blob
    const u = URL.createObjectURL(typed)
    setUrl(u)
    return () => {
      URL.revokeObjectURL(u)
      setUrl(null)
    }
  }, [blob, type])
  return url
}

function BlobView({ blob, kind, path, height }: { blob: Blob; kind: 'pdf' | 'image'; path: string; height: number }) {
  const url = useObjectUrl(blob, kind === 'pdf' ? 'application/pdf' : null)
  const name = path.split('/').pop() ?? path
  if (!url) return <Skeleton height={160} />
  return (
    <div className={styles.blob}>
      <div className={styles.toolbar}>
        <Mono muted>{name}</Mono>
        <a className={styles.open} href={url} target="_blank" rel="noreferrer">
          Abrir en otra pestaña <ExternalLink aria-hidden />
        </a>
      </div>
      {kind === 'pdf' ? <iframe className={styles.frame} src={url} title={name} style={{ height }} /> : <img className={styles.image} src={url} alt={name} />}
    </div>
  )
}

/** Indents an XML document (falls back to the raw text when it does not parse). */
export function prettyXml(text: string): string {
  if (typeof DOMParser === 'undefined' || text.length > MAX_TEXT) return text
  const doc = new DOMParser().parseFromString(text, 'application/xml')
  if (doc.getElementsByTagName('parsererror').length) return text
  const out: string[] = []
  const walk = (el: Element, depth: number) => {
    const pad = '  '.repeat(depth)
    const attrs = [...el.attributes].map((a) => ` ${a.name}="${a.value}"`).join('')
    const children = [...el.childNodes].filter((n) => n.nodeType === 1 || (n.nodeType === 3 && n.textContent?.trim()))
    if (!children.length) return void out.push(`${pad}<${el.tagName}${attrs}/>`)
    if (children.length === 1 && children[0].nodeType === 3) return void out.push(`${pad}<${el.tagName}${attrs}>${children[0].textContent?.trim()}</${el.tagName}>`)
    out.push(`${pad}<${el.tagName}${attrs}>`)
    for (const c of children) {
      if (c.nodeType === 1) walk(c as Element, depth + 1)
      else out.push(`${pad}  ${c.textContent?.trim()}`)
    }
    out.push(`${pad}</${el.tagName}>`)
  }
  walk(doc.documentElement, 0)
  return out.join('\n')
}

function XmlView({ text, einvoice }: { text: string; einvoice: EInvoiceSummary | null }) {
  const pretty = useMemo(() => prettyXml(text), [text])
  return (
    <div className={styles.xml}>
      {einvoice && <EInvoiceView summary={einvoice} />}
      <details className={styles.raw} open={!einvoice}>
        <summary>XML {einvoice ? 'completo' : ''}</summary>
        <pre className={styles.pre}>{pretty}</pre>
      </details>
    </div>
  )
}

export function EInvoiceView({ summary: s }: { summary: EInvoiceSummary }) {
  const cur = s.currency ?? 'EUR'
  const money = (v: number | null) => (v === null ? null : <Amount cents={v} currency={cur} />)
  const items = [
    { label: 'Formato', value: `${s.format === 'cfdi' ? 'CFDI' : 'Facturae'} ${s.version ?? ''}`.trim() },
    { label: 'Número', value: [s.series, s.invoiceNumber].filter(Boolean).join(' ') || null, mono: true },
    { label: 'Fecha', value: formatDate(s.issueDate) },
    { label: 'Emisor', value: [s.seller.name, s.seller.taxId && `(${s.seller.taxId})`].filter(Boolean).join(' ') || null },
    { label: 'Destinatario', value: [s.buyer.name, s.buyer.taxId && `(${s.buyer.taxId})`].filter(Boolean).join(' ') || null },
    { label: 'Base', value: money(s.net) },
    { label: 'Impuestos', value: money(s.tax) },
    s.withheld ? { label: 'Retenido', value: money(s.withheld) } : null,
    { label: 'Total', value: money(s.total) },
    s.retention ? { label: 'Retención de garantía', value: money(s.retention) } : null,
    s.payable !== null ? { label: 'A pagar', value: money(s.payable) } : null,
    s.iban ? { label: 'IBAN', value: s.iban, mono: true } : null,
    s.corrects ? { label: 'Rectifica', value: [s.corrects.invoiceNumber, s.corrects.reason].filter(Boolean).join(' · ') } : null,
    s.cfdi?.uuid ? { label: 'UUID', value: s.cfdi.uuid, mono: true } : null,
    s.lines.length ? { label: 'Líneas', value: String(s.lines.length) } : null,
  ].filter((x): x is NonNullable<typeof x> => !!x)
  return <KeyValue items={items} labelWidth={130} className={styles.summary} />
}

export function EmailView({ message: m }: { message: InboxMessage }) {
  return (
    <div className={styles.email}>
      <div className={styles.emailHead}>
        <Mail aria-hidden className={styles.emailIcon} />
        <div className={styles.emailFields}>
          <p className={styles.subject}>{m.subject ?? (m.source ? m.source : `Recibido por ${m.channel}`)}</p>
          <KeyValue
            labelWidth={84}
            items={[
              m.from ? { label: 'De', value: m.from, mono: true } : null,
              m.to ? { label: 'Para', value: m.to, mono: true } : null,
              { label: 'Canal', value: m.channel },
              { label: 'Recibido', value: formatDateTime(m.received_at) },
              { label: 'Buzón', value: m.mailbox, mono: true },
              m.uploaded_by ? { label: 'Subido por', value: m.uploaded_by } : null,
            ].filter((x): x is NonNullable<typeof x> => !!x)}
          />
        </div>
      </div>
      {m.body && <p className={styles.body}>{m.body}</p>}
      {m.attachments.length > 0 && (
        <p className={styles.attachments}>
          <Paperclip aria-hidden />
          {m.attachments.map((a) => (
            <Mono key={a}>{a}</Mono>
          ))}
        </p>
      )}
    </div>
  )
}
