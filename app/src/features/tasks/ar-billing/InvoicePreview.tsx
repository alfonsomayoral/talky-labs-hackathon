// Invoice preview of one billing item next to its source document: lines, tax, retention, deductions,
// DIR3, the «a origen − anterior» of a certification and, when not billed, the WIP accrual in Cierre.
import type { ReactNode } from 'react'
import { ArrowUpRight, CircleAlert, CircleCheck, X } from 'lucide-react'
import { Amount, Button, Card, IconButton, KeyValue, Mono } from '@/components'
import type { CloseRow, DatasetApi } from '@/domain/types'
import { formatDate, formatMonth, formatNumber, formatPercent } from '@/lib/format'
import { BILLING_TYPE_LABELS, DocumentViewer, JournalEntryView } from '@/features/item/kit'
import { useOpenItem } from '@/shell/useOpenItem'
import { certificationCalc, invoiceFigures, wipFor, type BillingListRow, type CertificationCalc, type InvoiceFigures } from './billingModel'
import styles from './ArBilling.module.css'

const DEDUCTION_LABELS: Record<string, string> = {
  MX5MILL: '5 al millar',
  ADV_AMORT: 'Amortización del anticipo',
}

const DAY_MS = 86_400_000
const daysBetween = (from: string, to: string) => Math.round((Date.parse(to) - Date.parse(from)) / DAY_MS)

interface InvoicePreviewProps {
  entry: BillingListRow
  api: DatasetApi
  closeRows: readonly CloseRow[]
  onClose: () => void
}

export function InvoicePreview({ entry, api, closeRows, onClose }: InvoicePreviewProps) {
  const openItem = useOpenItem()
  const { item, row, type, contract, customer, month, invoiceNumber } = entry
  const currency = item.currency ?? 'EUR'
  const inv = row?.invoice ?? null
  const docs = api.core.arInbox.billing.find((b) => b.item === item.key)?.files ?? []
  const wip = item.outcome === 'SKIP_PENDING_APPROVAL' ? wipFor(item.key, closeRows) : null
  const cert =
    type === 'OBRA_CERTIFICATION' && contract && month
      ? certificationCalc(contract, month, inv ? inv.net : (wip?.amount ?? null), api.core.billingHistory, api.core.salesContracts)
      : null
  const customerName = item.counterparty ?? (customer ? api.core.customers.find((c) => c.id === customer)?.name : null) ?? customer

  return (
    <Card
      className={styles.preview}
      title={
        <span className={styles.previewTitle}>
          {invoiceNumber ? <>Factura <Mono>{invoiceNumber}</Mono></> : 'Sin factura'}
          <Mono muted>{item.key}</Mono>
        </span>
      }
      description={[BILLING_TYPE_LABELS[type ?? ''] ?? type, contract, customerName].filter(Boolean).join(' · ')}
      actions={
        <>
          <Button size="sm" variant="secondary" trailingIcon={<ArrowUpRight />} onClick={() => openItem(item.id)}>
            Razonamiento
          </Button>
          <IconButton icon={<X />} label="Cerrar" size="sm" onClick={onClose} />
        </>
      }
    >
      <div className={styles.previewGrid}>
        <div className={styles.previewMain}>
          {item.outcome === 'SKIP_PENDING_APPROVAL' && (
            <div className={styles.callout} data-tone="warn">
              <CircleAlert aria-hidden />
              <div>
                <strong>Pendiente de aprobación de la Dirección Facultativa.</strong> No se factura este mes (<Mono>§3.1</Mono>).
                {wip ? (
                  <p className={styles.calloutLine}>
                    Obra pendiente de certificar registrada en Cierre: <Amount cents={wip.amount} currency={currency} />
                    <Button size="sm" variant="ghost" trailingIcon={<ArrowUpRight />} onClick={() => openItem(wip.id)}>
                      Ver en Cierre
                    </Button>
                  </p>
                ) : (
                  <p className={styles.calloutLine}>Falta su fila WIP_REVENUE en el cierre: la obra ejecutada queda sin reconocer.</p>
                )}
              </div>
            </div>
          )}

          {cert && <CertificationBlock cert={cert} currency={currency} billed={!!inv} />}

          {inv && (
            <>
              <KeyValue
                columns={2}
                labelWidth={104}
                items={[
                  { label: 'Fecha', value: formatDate(inv.date) },
                  {
                    label: 'Vencimiento',
                    value: (
                      <>
                        {formatDate(inv.due_date)}
                        {inv.date && inv.due_date && <span className={styles.muted}> · {formatNumber(daysBetween(inv.date, inv.due_date))} días</span>}
                      </>
                    ),
                  },
                  {
                    label: 'Impuesto',
                    value: (
                      <>
                        <Mono>{inv.tax_code}</Mono> <span className={styles.muted}>{api.core.taxCodes.tax_codes[inv.tax_code]?.desc ?? ''}</span>
                      </>
                    ),
                  },
                  { label: 'Moneda', value: <Mono>{currency}</Mono> },
                  {
                    label: 'FACe',
                    value:
                      inv.face && typeof inv.face === 'object' ? (
                        <span className={styles.dir3}>
                          <span>Oficina contable <Mono>{inv.face.oficina_contable}</Mono></span>
                          <span>Órgano gestor <Mono>{inv.face.organo_gestor}</Mono></span>
                          <span>Unidad tramitadora <Mono>{inv.face.unidad_tramitadora}</Mono></span>
                        </span>
                      ) : (
                        <span className={styles.muted}>No aplica</span>
                      ),
                  },
                ]}
              />
              <InvoiceLines lines={inv.lines} currency={currency} />
              <Totals figures={invoiceFigures(inv)} taxCode={inv.tax_code} currency={currency} />
            </>
          )}

        </div>

        <div className={styles.previewDoc}>
          <div className={styles.docLabel}>Documento recibido</div>
          {docs.length ? docs.map((path) => <DocumentViewer key={path} path={path} height={640} />) : <p className={styles.muted}>Sin documento en la bandeja.</p>}
        </div>
      </div>
      {row?.journal_entry && <JournalEntryView className={styles.entry} entry={row.journal_entry} currency={currency} title="Asiento de la factura" />}
    </Card>
  )
}

function CertificationBlock({ cert, currency, billed }: { cert: CertificationCalc; currency: string; billed: boolean }) {
  return (
    <div className={styles.cert}>
      <div className={styles.blockTitle}>Certificación a origen − anterior</div>
      <dl className={styles.certRows}>
        <dt>
          Anterior
          <span className={styles.muted}>
            {cert.previous
              ? ` · cert. nº ${cert.previous.number} de ${formatMonth(cert.previous.month)}${cert.previous.approvedOn ? `, aprobada el ${formatDate(cert.previous.approvedOn)}` : ''}`
              : ' · primera certificación'}
          </span>
        </dt>
        <dd>
          <Amount cents={cert.anterior} currency={currency} />
        </dd>
        <dt>
          Presente<span className={styles.muted}>{billed ? ' · base de la factura' : ' · obra pendiente de certificar'}</span>
        </dt>
        <dd>
          <Amount cents={cert.presente} currency={currency} />
        </dd>
        <dt className={styles.strong}>A origen</dt>
        <dd className={styles.strong}>
          <Amount cents={cert.aOrigen} currency={currency} />
        </dd>
      </dl>
      {cert.contractValue !== null && (
        <p className={styles.note}>
          Contrato por <Amount cents={cert.contractValue} currency={currency} />
          {cert.executed !== null && <> · {formatPercent(cert.executed)} ejecutado a origen</>}
        </p>
      )}
      {cert.pendingMonths.length > 0 && (
        <p className={styles.note}>
          Incluye la obra de {cert.pendingMonths.map(formatMonth).join(', ')}, que quedó pendiente de aprobación: el anterior es el último acumulado aprobado.
        </p>
      )}
    </div>
  )
}

function InvoiceLines({ lines, currency }: { lines: { description: string; amount: number; account: string; wbs?: string | null; cost_center?: string | null }[]; currency: string }) {
  return (
    <table className={styles.lines}>
      <thead>
        <tr>
          <th>Concepto</th>
          <th>Objeto de coste</th>
          <th>Cuenta</th>
          <th className={styles.num}>Importe</th>
        </tr>
      </thead>
      <tbody>
        {lines.map((l, i) => (
          <tr key={i}>
            <td>{l.description}</td>
            <td>
              <Mono muted>{l.wbs ?? l.cost_center ?? '—'}</Mono>
            </td>
            <td>
              <Mono muted>{l.account}</Mono>
            </td>
            <td className={styles.num}>
              <Amount cents={l.amount} currency={currency} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Totals({ figures: f, taxCode, currency }: { figures: InvoiceFigures; taxCode: string; currency: string }) {
  return (
    <div className={styles.totals}>
      <dl className={styles.totalRows}>
        <dt>Base imponible</dt>
        <dd>
          <Amount cents={f.net} currency={currency} />
        </dd>
        <dt>
          + Impuesto <Mono muted>{taxCode}</Mono>
        </dt>
        <dd>
          <Amount cents={f.tax} currency={currency} />
        </dd>
        <dt className={styles.strong}>Total</dt>
        <dd className={styles.strong}>
          <Amount cents={f.gross} currency={currency} />
        </dd>
        {f.retention !== 0 && (
          <>
            <dt>
              − Retención de garantía <Mono muted>43000900</Mono>
            </dt>
            <dd>
              <Amount cents={-f.retention} currency={currency} />
            </dd>
          </>
        )}
        {f.deductions.map((x) => (
          <Deduction key={x.code} label={DEDUCTION_LABELS[x.code] ?? x.code} account={x.account} amount={x.amount} currency={currency} />
        ))}
        <dt className={styles.strong}>A cobrar</dt>
        <dd className={styles.strong}>
          <Amount cents={f.payable} currency={currency} />
        </dd>
      </dl>
      <ul className={styles.checks}>
        <Check ok={f.linesOk}>
          {f.linesOk ? 'Las líneas suman la base' : <>Las líneas suman <Amount cents={f.linesTotal} currency={currency} />, no la base</>}
        </Check>
        <Check ok={f.payableOk}>
          {f.payableOk ? 'A cobrar = total − retención − deducciones' : <>A cobrar debería ser <Amount cents={f.expectedPayable} currency={currency} /></>}
        </Check>
      </ul>
    </div>
  )
}

function Deduction({ label, account, amount, currency }: { label: string; account: string | null; amount: number; currency: string }) {
  return (
    <>
      <dt>
        − {label} {account && <Mono muted>{account}</Mono>}
      </dt>
      <dd>
        <Amount cents={-amount} currency={currency} />
      </dd>
    </>
  )
}

function Check({ ok, children }: { ok: boolean; children: ReactNode }) {
  return (
    <li data-tone={ok ? 'ok' : 'danger'}>
      {ok ? <CircleCheck aria-hidden /> : <CircleAlert aria-hidden />}
      <span>{children}</span>
    </li>
  )
}
