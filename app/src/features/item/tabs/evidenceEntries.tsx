// Evidence of an item for the Evidencia tab: its references (item + events) plus task-specific extras.

import type { ApRow, ArCashRow, EvidenceRef, JournalEntry, PurchaseOrder } from '@/domain/types'
import { useDatasetStore } from '@/data/stores'
import { Amount, Button, Mono, Skeleton } from '@/components'
import { formatDate } from '@/lib/format'
import {
  ApMasterCompare,
  BookLine,
  ErpRecord,
  erpFileLabel,
  evidenceKey,
  evidenceLabel,
  findErpRecord,
  findStatementLine,
  uniqueRefs,
  useAsync,
  type EvidenceEntry,
  type ItemContext,
} from '../kit'
import styles from './tabs.module.css'

const GROUP: Record<EvidenceRef['kind'], string> = {
  doc: 'Documentos',
  bank: 'Banco',
  journal: 'Libro',
  erp: 'Maestros y registros',
  precedent: 'Precedentes',
}
const RELATED = 'Relacionado'
const GROUP_ORDER = ['Documentos', 'Banco', 'Libro', 'Maestros y registros', RELATED, 'Precedentes']

function refSubtitle(ctx: ItemContext, ref: EvidenceRef): string | undefined {
  const { core } = ctx
  switch (ref.kind) {
    case 'doc':
      return ref.locator ?? ref.path.split('/').slice(0, -1).join('/')
    case 'bank': {
      const l = findStatementLine(core, ref.bank_line)?.line
      return l ? `${formatDate(l.booking_date)} · ${l.text}` : ref.account
    }
    case 'erp': {
      const rec = findErpRecord(core, ref.file, ref.key) as Record<string, unknown> | null
      if (!rec || Array.isArray(rec)) return Array.isArray(rec) ? `${rec.length} registros` : 'No está en los datos cargados'
      return String(rec.name ?? rec.text ?? rec.customer ?? rec.vendor ?? rec.number ?? '') || undefined
    }
    default:
      return undefined
  }
}

export function buildEvidenceEntries(ctx: ItemContext, openItem: (id: string) => void): EvidenceEntry[] {
  const { item, events, rows, core } = ctx
  const refs = uniqueRefs([...item.evidence, ...events.flatMap((e) => e.evidence ?? [])])
  const row = (rows[0] ?? {}) as Record<string, unknown>
  const out: EvidenceEntry[] = refs.map((ref) => {
    const entry: EvidenceEntry = {
      key: evidenceKey(ref),
      kind: ref.kind,
      group: GROUP[ref.kind],
      title: ref.kind === 'erp' ? `${erpFileLabel(ref.file)} ${ref.key}` : evidenceLabel(ref),
      subtitle: refSubtitle(ctx, ref),
      ref,
    }
    if (item.task === 'ap' && ref.kind === 'erp' && ref.file === 'erp/vendors.jsonl') {
      entry.render = () => (
        <div className={styles.related}>
          <ApMasterCompare row={row as Partial<ApRow>} />
          <ErpRecord file={ref.file} recordKey={ref.key} />
        </div>
      )
    }
    if (ref.kind === 'erp' && ref.file === 'erp/purchase_orders.jsonl') {
      const items = (Array.isArray(row.lines) ? (row.lines as ApRow['lines']) : []).filter((l) => l.po === ref.key).map((l) => Number(l.po_item))
      entry.render = () => <PurchaseOrderEvidence po={ref.key} items={items} />
    }
    return entry
  })
  const add = (e: EvidenceEntry) => {
    if (!out.some((x) => x.key === e.key)) out.push(e)
  }

  switch (item.task) {
    case 'ap': {
      const dup = typeof row.duplicate_of === 'string' ? row.duplicate_of : null
      if (dup && ctx.derived.itemsById.has(`ap:${dup}`)) {
        add({
          key: `related:dup:${dup}`,
          kind: 'related',
          group: RELATED,
          title: `Documento original ${dup}`,
          subtitle: ctx.derived.itemsById.get(`ap:${dup}`)?.title,
          render: () => (
            <Button size="sm" onClick={() => openItem(`ap:${dup}`)}>
              Abrir la partida original
            </Button>
          ),
        })
      }
      break
    }
    case 'bank_rec': {
      const account = item.key.split('/')[0]
      add({ key: `erp:erp/bank_accounts.jsonl:${account}`, kind: 'erp', group: GROUP.erp, title: `Cuenta bancaria ${account}`, subtitle: core.bankAccounts.find((b) => b.id === account)?.bank, ref: { kind: 'erp', file: 'erp/bank_accounts.jsonl', key: account } })
      break
    }
    case 'ar_cash': {
      const residuals = Array.isArray((row as Partial<ArCashRow>).residuals) ? (row as ArCashRow).residuals : []
      for (const r of residuals) {
        if (!r.invoice) continue
        add({ key: `erp:erp/ar_invoices.jsonl:${r.invoice}`, kind: 'erp', group: GROUP.erp, title: `Factura emitida ${r.invoice}`, ref: { kind: 'erp', file: 'erp/ar_invoices.jsonl', key: r.invoice } })
        if (r.type === 'FACTORED_MISDIRECTED') {
          add({ key: `erp:erp/factoring_assignments.jsonl:${r.invoice}`, kind: 'erp', group: GROUP.erp, title: `Cesión a factor de ${r.invoice}`, ref: { kind: 'erp', file: 'erp/factoring_assignments.jsonl', key: r.invoice } })
        }
        if (r.type === 'PENALTY') {
          add({ key: `erp:erp/penalty_notices.jsonl:${r.invoice}`, kind: 'erp', group: GROUP.erp, title: `Penalidad sobre ${r.invoice}`, ref: { kind: 'erp', file: 'erp/penalty_notices.jsonl', key: r.invoice } })
        }
      }
      break
    }
    case 'ic': {
      const pair = item.key.split('/')[0].split('-')
      const accounts = typeof row.account === 'string' ? row.account.split('/') : (core.tasks.intercompany?.accounts ?? [])
      add({
        key: `related:ic-journal:${item.key}`,
        kind: 'related',
        group: RELATED,
        title: 'Apuntes intragrupo del mes',
        subtitle: `${pair.join(' – ')} · ${accounts.join(', ')}`,
        render: () => <IcJournal pair={pair} accounts={accounts} />,
      })
      break
    }
    case 'close': {
      const type = item.outcome
      if (type === 'ACCRUAL' && typeof row.vendor === 'string') {
        const vendor = row.vendor
        add({ key: `related:history:${vendor}`, kind: 'related', group: RELATED, title: 'Histórico de facturas del proveedor', subtitle: vendor, render: () => <VendorHistory vendor={vendor} company={item.company} /> })
      }
      if (type === 'PREPAID' && typeof row.invoice === 'string') {
        const inv = core.apInvoices.find((i) => i.doc_id === row.invoice)
        if (inv?.journal_entry) add({ key: `journal:${inv.journal_entry}`, kind: 'journal', group: GROUP.journal, title: `Asiento de la factura ${inv.doc_id}`, subtitle: inv.journal_entry, render: () => <BookLine bookLine={inv.journal_entry} /> })
      }
      if ((type === 'BAD_DEBT' || type === 'DOUBTFUL_RECLASS') && typeof row.customer === 'string') {
        add({ key: `erp:erp/open_items.jsonl:${row.customer}`, kind: 'erp', group: GROUP.erp, title: `Partidas abiertas de ${row.customer}`, ref: { kind: 'erp', file: 'erp/open_items.jsonl', key: row.customer } })
      }
      if (type === 'FX_REVAL' && typeof row.currency === 'string' && row.currency !== 'EUR') {
        add({ key: `erp:erp/fx_rates.jsonl:${row.currency}`, kind: 'erp', group: GROUP.erp, title: `Tipos de cambio ${row.currency}`, ref: { kind: 'erp', file: 'erp/fx_rates.jsonl', key: row.currency } })
      }
      break
    }
    default:
      break
  }
  return out.sort((a, b) => GROUP_ORDER.indexOf(a.group) - GROUP_ORDER.indexOf(b.group))
}

// ---------------------------------------------------------------- extra viewers
function PurchaseOrderEvidence({ po, items }: { po: string; items: number[] }) {
  const api = useDatasetStore((s) => s.api)
  const order = api?.core.purchaseOrders.find((p) => p.id === po) as PurchaseOrder | undefined
  const receipts = useAsync(async () => (api ? api.goodsReceipts({ po }) : []), [api, po])
  const cur = order?.currency ?? 'EUR'
  return (
    <div className={styles.related}>
      {order ? (
        <>
          <p className={styles.note}>
            {order.text} · {order.type} · creado el {formatDate(order.created_on)}
          </p>
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Pos.</th>
                  <th>Material</th>
                  <th className={styles.num}>Cantidad</th>
                  <th className={styles.num}>Precio</th>
                  <th>Cuenta · objeto</th>
                </tr>
              </thead>
              <tbody>
                {order.items.map((it) => (
                  <tr key={it.item} className={items.includes(it.item) ? styles.highlightRow : undefined}>
                    <td>
                      <Mono>{it.item}</Mono>
                    </td>
                    <td>{it.description}</td>
                    <td className={styles.num}>
                      {(it.quantity_milli / 1000).toLocaleString('es-ES')} {it.uom}
                    </td>
                    <td className={styles.num}>
                      <Amount cents={it.unit_price} currency={cur} />
                    </td>
                    <td>
                      <Mono>{[it.gl_account, it.wbs ?? it.cost_center].filter(Boolean).join(' · ')}</Mono>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className={styles.note}>El pedido {po} no está en los datos cargados.</p>
      )}
      <h5 className={styles.note}>Entradas de mercancía</h5>
      {receipts.status === 'loading' && <Skeleton lines={2} />}
      {receipts.status === 'error' && <p role="alert" className={styles.note}>No se pudieron leer: {receipts.error}</p>}
      {receipts.status === 'ready' &&
        (receipts.data.length ? (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Entrada</th>
                  <th>Pos.</th>
                  <th>Fecha</th>
                  <th className={styles.num}>Cantidad</th>
                  <th className={styles.num}>Valor</th>
                </tr>
              </thead>
              <tbody>
                {receipts.data.map((g) => (
                  <tr key={g.id}>
                    <td>
                      <Mono>{g.id}</Mono>
                    </td>
                    <td>
                      <Mono>{g.po_item}</Mono>
                    </td>
                    <td>{formatDate(g.posting_date)}</td>
                    <td className={styles.num}>{(g.quantity_milli / 1000).toLocaleString('es-ES')}</td>
                    <td className={styles.num}>
                      <Amount cents={g.amount} currency={cur} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className={styles.note}>Sin entradas registradas para este pedido.</p>
        ))}
    </div>
  )
}

function VendorHistory({ vendor, company }: { vendor: string; company: string | null }) {
  const core = useDatasetStore((s) => s.api?.core ?? null)
  const history = (core?.apInvoices ?? []).filter((i) => i.vendor === vendor && (!company || i.company === company)).sort((a, b) => b.issue_date.localeCompare(a.issue_date))
  if (!history.length) return <p className={styles.note}>Sin facturas previas de {vendor} en ap_invoices.</p>
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Documento</th>
            <th>Número</th>
            <th>Emitida</th>
            <th className={styles.num}>Base</th>
          </tr>
        </thead>
        <tbody>
          {history.slice(0, 24).map((i) => (
            <tr key={i.doc_id}>
              <td>
                <Mono>{i.doc_id}</Mono>
              </td>
              <td>
                <Mono>{i.number}</Mono>
              </td>
              <td>{formatDate(i.issue_date)}</td>
              <td className={styles.num}>
                <Amount cents={i.net} currency={i.currency} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function IcJournal({ pair, accounts }: { pair: string[]; accounts: string[] }) {
  const api = useDatasetStore((s) => s.api)
  const month = api?.core.tasks.close.month ?? null
  const state = useAsync(async () => {
    if (!api || !month) return []
    const [y, m] = month.split('-').map(Number)
    const to = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10)
    const results = await Promise.all(
      pair.flatMap((company) => accounts.map((account) => api.queryJournal({ company, account, from: `${month}-01`, to, limit: 200 }))),
    )
    const seen = new Set<string>()
    const out: { entry: JournalEntry; line: JournalEntry['lines'][number] }[] = []
    for (const r of results) {
      for (const e of r.entries) {
        const other = pair.find((p) => p !== e.company) ?? ''
        for (const l of e.lines) {
          if (!accounts.includes(l.account) || !String(l.partner ?? '').includes(other)) continue
          const k = `${e.id}#${l.line}`
          if (seen.has(k)) continue
          seen.add(k)
          out.push({ entry: e, line: l })
        }
      }
    }
    return out.sort((a, b) => a.entry.posting_date.localeCompare(b.entry.posting_date)).slice(0, 60)
  }, [api, month, pair.join(','), accounts.join(',')])
  if (state.status === 'loading') return <Skeleton lines={3} />
  if (state.status === 'error') return <p role="alert" className={styles.note}>No se pudo consultar el diario: {state.error}</p>
  if (!state.data.length) return <p className={styles.note}>Sin apuntes entre {pair.join(' y ')} en esas cuentas este mes.</p>
  const currency = (company: string) => api?.core.companies.find((c) => c.code === company)?.currency ?? 'EUR'
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Apunte</th>
            <th>Fecha</th>
            <th>Cuenta · socio</th>
            <th className={styles.num}>Debe</th>
            <th className={styles.num}>Haber</th>
          </tr>
        </thead>
        <tbody>
          {state.data.map(({ entry, line }) => (
            <tr key={`${entry.id}#${line.line}`} title={line.text}>
              <td>
                <Mono>{`${entry.id}#${line.line}`}</Mono>
              </td>
              <td>{formatDate(entry.posting_date)}</td>
              <td>
                <Mono>{`${line.account} · ${line.partner ?? '—'}`}</Mono>
              </td>
              <td className={styles.num}>{line.debit ? <Amount cents={line.debit} currency={currency(entry.company)} /> : null}</td>
              <td className={styles.num}>{line.credit ? <Amount cents={line.credit} currency={currency(entry.company)} /> : null}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

