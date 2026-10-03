// Ficha of one AP document: the document beside what the agent extracted, checked against the master,
// the PO and the goods receipts, plus payee, payment block and the duplicate link.
import { useMemo } from 'react'
import { AlertTriangle, ArrowUpRight, Check, CircleHelp, Info, X } from 'lucide-react'
import clsx from 'clsx'
import { Amount, Badge, Button, KeyValue, Mono, Pill, Section, Skeleton } from '@/components'
import type { ApRow, DatasetApi, WorkItem } from '@/domain/types'
import { AP_ACTION_CATALOG, AP_DECISION_CATALOG, AP_DOCUMENT_TYPE_CATALOG, AP_PAYEE_CATALOG, AP_REASON_CATALOG } from '@/domain/catalog/policy'
import { useItemEvents } from '@/engine'
import { apCascade, PolicyCascade } from '@/features/item/kit'
import { formatDate, formatNumber } from '@/lib/format'
import { useOpenItem } from '@/shell/useOpenItem'
import { DocumentPane } from './DocumentPane'
import { actionDetails, DECISION_TONE, duplicateTarget, duplicatesOf, lineMatches, masterCompare, textDiff, type CompareState, type LineState } from './model'
import { useDocContext } from './useDocContext'
import styles from './Ap.module.css'

interface Props {
  api: DatasetApi
  item: WorkItem
  row: ApRow
  rows: readonly ApRow[]
  onSelectDoc: (docId: string) => void
}

const STATE_ICON: Record<CompareState, { icon: typeof Check; label: string; className: string }> = {
  match: { icon: Check, label: 'Coincide', className: styles.ok },
  mismatch: { icon: X, label: 'No coincide', className: styles.bad },
  explained: { icon: Info, label: 'Distinto pero justificado', className: styles.info },
  unknown: { icon: CircleHelp, label: 'Sin dato para comparar', className: styles.muted },
}

const LINE_STATE: Record<LineState, { label: string; tone: 'ok' | 'warn' | 'danger' | 'neutral' | 'info' }> = {
  no_po: { label: 'Sin pedido', tone: 'neutral' },
  ok: { label: 'Cuadra', tone: 'ok' },
  within_tolerance: { label: 'En tolerancia', tone: 'info' },
  price_variance: { label: 'Diferencia de precio', tone: 'danger' },
  not_received: { label: 'Sin entrada', tone: 'danger' },
  po_missing: { label: 'Pedido no encontrado', tone: 'warn' },
}

export function ApDocCard({ api, item, row, rows, onSelectDoc }: Props) {
  const { core } = api
  const openItem = useOpenItem()
  const inbox = useMemo(() => core.apInbox.find((d) => d.docId === row.doc_id) ?? null, [core.apInbox, row.doc_id])
  const files = useMemo(() => inbox?.files ?? [], [inbox])
  const ctx = useDocContext(api, row, files)
  const vendor = core.vendors.find((v) => v.id === row.vendor_id) ?? null
  const company = core.companies.find((c) => c.code === row.company) ?? null
  const currency = row.currency ?? company?.currency ?? 'EUR'

  const compare = useMemo(
    () => masterCompare({ row, vendor, company, einvoice: ctx.einvoice, certificates: core.contractorCertificates, sender: inbox?.message.from ?? inbox?.message.uploaded_by ?? null }),
    [row, vendor, company, ctx.einvoice, core.contractorCertificates, inbox],
  )
  const lines = useMemo(() => lineMatches(row.lines ?? [], core.purchaseOrders, ctx.receipts), [row.lines, core.purchaseOrders, ctx.receipts])
  const hasPo = lines.some((l) => l.po)
  const dup = duplicateTarget(row.duplicate_of, rows, core)
  const corrects = typeof row.credit_note_of === 'string' ? row.credit_note_of : null
  const copies = duplicatesOf(row.doc_id, rows)
  const decision = AP_DECISION_CATALOG[row.decision]
  const events = useItemEvents(item.id)
  const cascade = useMemo(() => apCascade(row, events), [row, events])

  return (
    <article className={styles.card} aria-label={`Ficha de ${row.doc_id}`}>
      <header className={styles.cardHeader}>
        <div className={styles.cardTitle}>
          <Mono>{row.doc_id}</Mono>
          <span className={styles.cardType}>{AP_DOCUMENT_TYPE_CATALOG[row.document_type]?.label ?? row.document_type}</span>
          <Badge tone={DECISION_TONE[row.decision] ?? 'neutral'}>{decision?.label ?? row.decision}</Badge>
          {decision && <Mono muted>{decision.section}</Mono>}
          {row.reasons.map((r) => (
            <Pill key={r} tone={r === 'BANK_DETAILS_CHANGED' ? 'danger' : 'neutral'}>
              {AP_REASON_CATALOG[r as keyof typeof AP_REASON_CATALOG]?.label ?? r}
            </Pill>
          ))}
        </div>
        <Button size="sm" variant="secondary" trailingIcon={<ArrowUpRight />} onClick={() => openItem(item.id)}>
          Razonamiento y asiento
        </Button>
      </header>

      <div className={styles.cardBody}>
        <DocumentPane doc={inbox} />

        <div className={styles.cardFacts}>
          <Section title="Cabecera extraída">
            <KeyValue
              columns={2}
              labelWidth={110}
              items={[
                { label: 'Sociedad', value: row.company ?? '—', mono: true },
                { label: 'Proveedor', value: vendor ? `${vendor.id} · ${vendor.name}` : (row.vendor_id ?? 'Sin alta') },
                { label: 'Factura', value: row.invoice_number ?? '—', mono: true },
                { label: 'Fecha', value: formatDate(row.invoice_date) },
                { label: 'Base', value: <Amount cents={row.net} currency={currency} /> },
                { label: 'IVA', value: <Amount cents={row.tax} currency={currency} /> },
                { label: 'Total', value: <Amount cents={row.gross} currency={currency} /> },
                { label: 'Retención', value: <Amount cents={row.withholding} currency={currency} /> },
                { label: 'Garantía', value: <Amount cents={row.retention} currency={currency} /> },
                { label: 'A pagar', value: <Amount cents={row.payable} currency={currency} /> },
              ]}
            />
          </Section>

          {cascade && (
            <Section title="Cascada de comprobaciones" description="§2.2 en orden: cada comprobación pasa hasta la que decide; las siguientes no se evalúan.">
              <PolicyCascade checks={cascade} />
            </Section>
          )}

          <Section title="Documento frente al maestro" description={ctx.einvoice ? 'Datos leídos de la factura electrónica.' : 'Sin factura electrónica: el documento es lo que extrajo el agente.'}>
            {ctx.status === 'loading' ? (
              <Skeleton lines={4} />
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Campo</th>
                    <th>Documento</th>
                    <th>Maestro</th>
                    <th aria-label="Resultado" />
                  </tr>
                </thead>
                <tbody>
                  {compare.map((f) => {
                    const s = STATE_ICON[f.state]
                    return (
                      <tr key={f.id} className={clsx(f.state === 'mismatch' && styles.rowBad)}>
                        <td>{f.label}</td>
                        <td className={styles.mono}>{f.state === 'mismatch' && f.document && f.master ? <Changed text={f.document} reference={f.master} /> : (f.document ?? '—')}</td>
                        <td className={styles.mono}>
                          {f.master ?? '—'}
                          {f.note && <div className={styles.note}>{f.note}</div>}
                        </td>
                        <td className={s.className} title={s.label}>
                          <s.icon aria-label={s.label} />
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </Section>

          {lines.length > 0 ? (
            <Section
              title={hasPo ? 'Casación línea a línea' : 'Imputación por línea'}
              count={lines.length}
              description={hasPo ? 'Importe facturado frente al valor de las entradas (cantidad × precio del pedido). Tolerancia: 2 % o 150 € por línea.' : 'Sin pedido: cada línea va a su cuenta de gasto u objeto de coste.'}
            >
              {ctx.status === 'loading' ? (
                <Skeleton lines={3} />
              ) : (
                <table className={styles.table}>
                  <thead>
                    <tr>
                      <th>Cuenta</th>
                      <th>Pedido</th>
                      <th>Entradas</th>
                      <th className={styles.num}>Facturado</th>
                      <th className={styles.num}>Recibido</th>
                      <th className={styles.num}>Diferencia</th>
                      <th>Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    {lines.map((l) => (
                      <tr key={l.index}>
                        <td className={styles.mono}>
                          {l.line.account}
                          {(l.line.wbs || l.line.cost_center) && <div className={styles.note}>{l.line.wbs ?? l.line.cost_center}</div>}
                        </td>
                        <td className={styles.mono}>
                          {l.po ? `${l.po}/${l.poItem ?? '—'}` : '—'}
                          {l.description && <div className={styles.note}>{l.description}</div>}
                        </td>
                        <td className={styles.mono}>
                          {l.receipts.length ? l.receipts.map((g) => g.id).join(', ') : '—'}
                          {l.receipts.length > 0 && <div className={styles.note}>{formatNumber(l.receivedQtyMilli / 1000, { decimals: 3 })} uds.</div>}
                        </td>
                        <td className={styles.num}>
                          <Amount cents={l.line.amount} currency={currency} />
                        </td>
                        <td className={styles.num}>{l.po ? <Amount cents={l.receivedValue} currency={currency} /> : '—'}</td>
                        <td className={styles.num}>{l.po && l.receipts.length ? <Amount cents={l.variance} currency={currency} signed /> : '—'}</td>
                        <td>
                          <Badge variant="outline" dot tone={LINE_STATE[l.state].tone}>
                            {LINE_STATE[l.state].label}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </Section>
          ) : null}

          {row.decision === 'NOT_INVOICE' ? (
            // Not an invoice: nothing is paid, so only what it changes in the vendor master matters.
            <Section title="Acción en el maestro">
              <KeyValue
                labelWidth={130}
                items={[
                  { label: 'Acción', value: row.action ? (AP_ACTION_CATALOG[row.action]?.label ?? row.action) : 'Ninguna' },
                  ...actionDetails(row.action_data).map((d) => ({
                    label: d.label,
                    value: d.kind === 'money' ? <Amount cents={Number(d.value)} currency={currency} /> : d.kind === 'mono' ? <Mono>{d.value}</Mono> : d.value,
                  })),
                ]}
              />
            </Section>
          ) : (
            <Section title="Pago">
              <KeyValue
                labelWidth={130}
                items={[
                  {
                    label: 'Beneficiario',
                    value: row.payee ? (
                      <span>
                        {AP_PAYEE_CATALOG[row.payee.type]?.label ?? row.payee.type}
                        {row.payee.type === 'FACTOR' && vendor?.alternative_payee && <span className={styles.note}> · {vendor.alternative_payee.name}</span>}
                        {row.payee.type === 'AEAT_EMBARGO' && vendor?.garnishments?.length ? <span className={styles.note}> · {vendor.garnishments.map((g) => g.ref).join(', ')}</span> : null}
                      </span>
                    ) : (
                      'El proveedor'
                    ),
                  },
                  {
                    label: 'Bloqueo de pago',
                    value: row.payment_block ? (
                      <Badge tone="warn" icon={<AlertTriangle />}>
                        Certificado art. 43 caducado
                      </Badge>
                    ) : (
                      'Sin bloqueo'
                    ),
                  },
                ]}
              />
            </Section>
          )}

          {corrects && (
            <Section title="Factura rectificada">
              <p className={styles.dupLine}>
                Abono sobre{' '}
                {rows.some((r) => r.doc_id === corrects) ? (
                  <button type="button" className={styles.link} onClick={() => onSelectDoc(corrects)}>
                    {corrects}
                  </button>
                ) : (
                  <Mono>{corrects}</Mono>
                )}
                : el asiento invierte el de la factura original con la misma cuenta y objeto de coste.
              </p>
            </Section>
          )}

          {(dup || copies.length > 0) && (
            <Section title="Duplicado">
              {dup?.kind === 'month' && (
                <p className={styles.dupLine}>
                  Duplicado de{' '}
                  <button type="button" className={styles.link} onClick={() => onSelectDoc(dup.docId)}>
                    {dup.docId}
                  </button>{' '}
                  ({dup.row.invoice_number}, <Amount cents={dup.row.gross} currency={dup.row.currency ?? currency} />), recibido este mes.
                </p>
              )}
              {dup?.kind === 'history' && (
                <p className={styles.dupLine}>
                  Duplicado de <Mono>{dup.docId}</Mono>, ya {dup.invoice ? 'contabilizada' : 'registrada'} antes de este mes
                  {dup.invoice && (
                    <>
                      : factura <Mono>{dup.invoice.number}</Mono> del {formatDate(dup.invoice.issue_date)}, <Amount cents={dup.invoice.gross} currency={dup.invoice.currency} />, asiento{' '}
                      <Mono>{dup.invoice.journal_entry}</Mono>
                    </>
                  )}
                  {!dup.invoice && dup.log && <> en el registro de documentos ({formatDate(dup.log.received_on)}, decisión {dup.log.decision})</>}.
                </p>
              )}
              {dup?.kind === 'missing' && (
                <p className={styles.dupLine}>
                  Marca <Mono>{dup.docId}</Mono> como original, pero no aparece ni en la bandeja del mes ni en el histórico.
                </p>
              )}
              {copies.length > 0 && (
                <p className={styles.dupLine}>
                  Este documento es el original de{' '}
                  {copies.map((id, i) => (
                    <span key={id}>
                      {i > 0 && ', '}
                      <button type="button" className={styles.link} onClick={() => onSelectDoc(id)}>
                        {id}
                      </button>
                    </span>
                  ))}
                  .
                </p>
              )}
            </Section>
          )}
        </div>
      </div>
    </article>
  )
}

/** A mismatching value with the part that differs from the master highlighted (a look-alike domain, a changed IBAN digit). */
function Changed({ text, reference }: { text: string; reference: string }) {
  const d = textDiff(text, reference)
  return (
    <>
      {d.before}
      {d.changed && <mark className={styles.changed}>{d.changed}</mark>}
      {d.after}
    </>
  )
}
