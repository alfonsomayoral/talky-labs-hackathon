// One receipt: what pays and what is settled (sources = uses), the raw bank record, the customer's
// open items before and after, and the adjustment that empties 55500000.
import { useMemo } from 'react'
import { ArrowUpRight, X } from 'lucide-react'
import { Amount, Button, Card, IconButton, KeyValue, Mono, toneColor } from '@/components'
import type { ArCashRow, ArResidualType, DatasetApi, JournalEntryOut, WorkItem } from '@/domain/types'
import { AR_RESIDUAL_CATALOG } from '@/domain/catalog/policy'
import { formatDate } from '@/lib/format'
import { findStatementLine, JournalEntryView, RawBankRecord } from '@/features/item/kit'
import { useOpenItem } from '@/shell/useOpenItem'
import { customerOpenItems, type Allocation, type Flow } from './cashModel'
import styles from './ArCash.module.css'

interface ReceiptDetailProps {
  item: WorkItem
  row: ArCashRow
  allocation: Allocation
  items: readonly WorkItem[]
  rows: readonly ArCashRow[]
  billingEntries: readonly JournalEntryOut[]
  api: DatasetApi
  onClose: () => void
}

export function ReceiptDetail({ item, row, allocation, items, rows, billingEntries, api, onClose }: ReceiptDetailProps) {
  const openItem = useOpenItem()
  const currency = item.currency ?? 'EUR'
  const statement = findStatementLine(api.core, item.key)
  const glAccount = statement ? api.core.bankAccounts.find((b) => b.id === statement.account)?.gl_account : null
  const openLines = useMemo(() => customerOpenItems(item, items, rows, billingEntries, api.core), [item, items, rows, billingEntries, api.core])
  const residuals = [...new Set((row?.residuals ?? []).map((r) => String(r.type)))]

  return (
    <Card
      title={
        <span className={styles.detailTitle}>
          Cobro <Mono>{item.key}</Mono>
        </span>
      }
      description={[item.counterparty ?? 'No es cliente', statement?.account, formatDate(item.date)].filter(Boolean).join(' · ')}
      actions={
        <>
          <Button size="sm" variant="secondary" trailingIcon={<ArrowUpRight />} onClick={() => openItem(item.id)}>
            Razonamiento
          </Button>
          <IconButton icon={<X />} label="Cerrar" size="sm" onClick={onClose} />
        </>
      }
    >
      <div className={styles.detailGrid}>
        <div className={styles.detailMain}>
          <KeyValue
            columns={2}
            labelWidth={96}
            items={[
              { label: 'Importe', value: <Amount cents={item.amount} currency={currency} /> },
              { label: 'Cuenta', value: <>{statement?.account ?? '—'} {glAccount && <Mono muted>{glAccount}</Mono>}</> },
              { label: 'Cliente', value: row?.customer ? <>{item.counterparty} <Mono muted>{row.customer}</Mono></> : <span className={styles.muted}>No es cliente</span> },
              { label: 'Concepto', value: <span className={styles.muted}>{statement?.line.text ?? '—'}</span> },
            ]}
          />
          <Flows allocation={allocation} currency={currency} />
          {residuals.map((type) => {
            const entry = AR_RESIDUAL_CATALOG[type as ArResidualType]
            return entry ? (
              <p key={type} className={styles.note}>
                <strong>{entry.label}.</strong> {entry.description} <Mono muted>{entry.section}</Mono>
              </p>
            ) : null
          })}
        </div>
        <div className={styles.detailSide}>
          <div className={styles.blockTitle}>Registro del extracto</div>
          <RawBankRecord bankLine={item.key} />
        </div>
      </div>

      <div className={styles.detailBlock}>
        <div className={styles.blockTitle}>Partidas abiertas del cliente en {item.company}, antes y después del cobro</div>
        {openLines.length ? (
          <table className={styles.open}>
            <thead>
              <tr>
                <th>Cuenta</th>
                <th>Asignación</th>
                <th className={styles.num}>Antes</th>
                <th className={styles.num}>Después</th>
              </tr>
            </thead>
            <tbody>
              {openLines.map((l) => (
                <tr key={`${l.account}|${l.assignment ?? ''}`} data-touched={l.touched || undefined}>
                  <td>
                    <Mono muted>{l.account}</Mono>
                  </td>
                  <td>{l.assignment ? <Mono>{l.assignment}</Mono> : <span className={styles.muted}>Sin asignación</span>}</td>
                  <td className={styles.num}>
                    <Amount cents={l.before} currency={currency} />
                  </td>
                  <td className={styles.num}>
                    <Amount cents={l.after} currency={currency} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className={styles.muted}>{row?.customer ? 'El cliente no tiene partidas abiertas en esta sociedad.' : 'El cobro no viene de un cliente: no toca partidas de clientes.'}</p>
        )}
      </div>

      {(row?.adjustment?.length ?? 0) > 0 && (
        <JournalEntryView className={styles.detailBlock} lines={row.adjustment} company={item.company} currency={currency} title="Asiento de ajuste" />
      )}
    </Card>
  )
}

/** Two aligned bars: what pays (cash, penalty, netting) and what is settled. Both add up to the same total. */
function Flows({ allocation, currency }: { allocation: Allocation; currency: string }) {
  const total = allocation.sources.reduce((s, f) => s + f.amount, 0)
  return (
    <div className={styles.flows}>
      <FlowRow title="Origen" flows={allocation.sources} total={total} currency={currency} />
      <FlowRow title="Destino" flows={allocation.uses} total={total} currency={currency} />
    </div>
  )
}

function FlowRow({ title, flows, total, currency }: { title: string; flows: Flow[]; total: number; currency: string }) {
  return (
    <div className={styles.flowRow}>
      <div className={styles.blockTitle}>{title}</div>
      <div className={styles.flowBar} role="img" aria-label={`${title}: ${flows.map((f) => f.label).join(', ')}`}>
        {flows.map((f) => (
          <span key={f.key} style={{ flexGrow: total ? f.amount / total : 1, background: toneColor(f.tone) }} />
        ))}
      </div>
      <ul className={styles.flowLegend}>
        {flows.map((f) => (
          <li key={f.key}>
            <span className={styles.dot} style={{ background: toneColor(f.tone) }} aria-hidden />
            <span className={styles.flowLabel}>
              {f.label}
              {f.ref && !f.label.includes(f.ref) && <Mono muted>{f.ref}</Mono>}
            </span>
            <Amount cents={f.amount} currency={currency} />
          </li>
        ))}
      </ul>
    </div>
  )
}
