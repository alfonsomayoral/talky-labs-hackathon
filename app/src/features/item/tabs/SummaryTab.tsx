import type { ReactNode } from 'react'
import type { ApRow, ArBillingRow, ArCashRow, BankRecRow, IcRow } from '@/domain/types'
import {
  AP_ACTION_CATALOG,
  AP_DECISION_CATALOG,
  AP_DOCUMENT_TYPE_CATALOG,
  AP_PAYEE_CATALOG,
  AP_REASON_CATALOG,
  AR_BILLING_OUTCOME_CATALOG,
  AR_RESIDUAL_CATALOG,
  BANK_CATEGORY_CATALOG,
  IC_CAUSE_CATALOG,
  accountLabel,
  outcomeEntry,
} from '@/domain/catalog/policy'
import { Amount, KeyValue, Mono, Section, type KeyValueItem } from '@/components'
import { formatDate } from '@/lib/format'
import { BILLING_TYPE_LABELS, findStatementLine, JsonView, matchShape, type ItemContext } from '../kit'
import styles from './tabs.module.css'

const str = (x: unknown): string | null => (typeof x === 'string' && x ? x : null)
const num = (x: unknown): number | null => (typeof x === 'number' && Number.isFinite(x) ? x : null)
const money = (cents: unknown, currency: string) => (num(cents) === null ? null : <Amount cents={cents as number} currency={currency} />)
const mono = (x: unknown) => (str(x) ? <Mono>{String(x)}</Mono> : null)
const compact = (items: (KeyValueItem | null | false | undefined | '')[]) => items.filter((x): x is KeyValueItem => !!x && x.value !== null && x.value !== undefined && x.value !== '')

/** The delivered row(s) of the item, task by task, plus the raw JSON. */
export function SummaryTab({ ctx }: { ctx: ItemContext }) {
  const body = (() => {
    switch (ctx.item.task) {
      case 'ap':
        return <ApSummary ctx={ctx} />
      case 'ar_billing':
        return <ArBillingSummary ctx={ctx} />
      case 'ar_cash':
        return <ArCashSummary ctx={ctx} />
      case 'bank_rec':
        return <BankSummary ctx={ctx} />
      case 'ic':
        return <IcSummary ctx={ctx} />
      case 'close':
        return <CloseSummary ctx={ctx} />
    }
  })()
  return (
    <div className={styles.stack}>
      {body}
      <details className={styles.raw}>
        <summary>Fila entregada ({ctx.rows.length === 1 ? 'JSON' : `${ctx.rows.length} filas`})</summary>
        <JsonView value={ctx.rows.length === 1 ? stripEntry(ctx.rows[0]) : ctx.rows.map(stripEntry)} depth={1} />
      </details>
    </div>
  )
}

const stripEntry = (row: Record<string, unknown>) => {
  const copy = { ...row }
  delete copy.journal_entry
  return copy
}

function Table({ head, rows, numeric = [] }: { head: string[]; rows: ReactNode[][]; numeric?: number[] }) {
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            {head.map((h, i) => (
              <th key={h} className={numeric.includes(i) ? styles.num : undefined}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {r.map((c, j) => (
                <td key={j} className={numeric.includes(j) ? styles.num : undefined}>
                  {c ?? <span className={styles.none}>—</span>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AccountCell({ account, ctx }: { account: unknown; ctx: ItemContext }) {
  const a = String(account ?? '')
  return (
    <span className={styles.account}>
      <Mono>{a}</Mono>
      <span className={styles.accountLabel}>{accountLabel(a, ctx.core.chartOfAccounts)}</span>
    </span>
  )
}

// ---------------------------------------------------------------- AP
function ApSummary({ ctx }: { ctx: ItemContext }) {
  const r = (ctx.rows[0] ?? {}) as Partial<ApRow>
  const cur = str(r.currency) ?? ctx.item.currency ?? 'EUR'
  const vendor = r.vendor_id ? ctx.core.vendors.find((v) => v.id === r.vendor_id) : undefined
  const payee = r.payee?.type ? AP_PAYEE_CATALOG[r.payee.type as keyof typeof AP_PAYEE_CATALOG] : null
  const lines = Array.isArray(r.lines) ? r.lines : []
  return (
    <>
      <Section title="Cabecera">
        <KeyValue
          columns={2}
          labelWidth={110}
          items={compact([
            { label: 'Documento', value: AP_DOCUMENT_TYPE_CATALOG[r.document_type as keyof typeof AP_DOCUMENT_TYPE_CATALOG]?.label ?? str(r.document_type) },
            { label: 'Decisión', value: AP_DECISION_CATALOG[r.decision as keyof typeof AP_DECISION_CATALOG]?.label ?? str(r.decision) },
            (r.reasons?.length ?? 0) > 0 && { label: 'Motivos', value: r.reasons!.map((x) => AP_REASON_CATALOG[x as keyof typeof AP_REASON_CATALOG]?.label ?? x).join(', ') },
            { label: 'Sociedad', value: mono(r.company) },
            { label: 'Proveedor', value: vendor ? `${vendor.id} · ${vendor.name}` : (str(r.vendor_id) ?? 'Sin alta en el maestro') },
            { label: 'Nº factura', value: mono(r.invoice_number) },
            { label: 'Fecha', value: r.invoice_date ? formatDate(r.invoice_date) : null },
            { label: 'Vencimiento', value: str(r.due_date) ? formatDate(String(r.due_date)) : null },
            { label: 'Moneda', value: str(r.currency) },
            { label: 'Base', value: money(r.net, cur) },
            { label: 'IVA', value: money(r.tax, cur) },
            { label: 'Total', value: money(r.gross, cur) },
            num(r.withholding) ? { label: 'Retención fiscal', value: money(r.withholding, cur) } : null,
            num(r.retention) ? { label: 'Garantía', value: money(r.retention, cur) } : null,
            { label: 'A pagar', value: money(r.payable, cur) },
            str(r.duplicate_of) && { label: 'Duplicado de', value: mono(r.duplicate_of) },
            payee && { label: 'Beneficiario', value: payee.label },
            str(r.payment_block) && { label: 'Bloqueo de pago', value: 'Certificado art. 43 caducado' },
            str(r.action) && { label: 'Acción', value: AP_ACTION_CATALOG[r.action as keyof typeof AP_ACTION_CATALOG]?.label ?? r.action },
          ])}
        />
      </Section>
      {lines.length > 0 && (
        <Section title="Líneas" count={lines.length}>
          <Table
            head={['Cuenta', 'Objeto de coste', 'IVA', 'Pedido', 'Importe']}
            numeric={[4]}
            rows={lines.map((l) => [
              <AccountCell key="a" account={l.account} ctx={ctx} />,
              mono([l.cost_center, l.wbs].filter(Boolean).join(' · ')),
              mono(l.tax_code),
              l.po ? <Mono key="po">{`${l.po}${l.po_item ? ` / ${l.po_item}` : ''}`}</Mono> : null,
              money(l.amount, cur),
            ])}
          />
        </Section>
      )}
    </>
  )
}

// ---------------------------------------------------------------- AR billing
function ArBillingSummary({ ctx }: { ctx: ItemContext }) {
  const r = (ctx.rows[0] ?? {}) as Partial<ArBillingRow> & Record<string, unknown>
  const inv = r.invoice ?? null
  const cur = str(inv?.currency) ?? ctx.item.currency ?? 'EUR'
  const customer = str(r.customer) ? ctx.core.customers.find((c) => c.id === r.customer) : undefined
  const lines = Array.isArray(inv?.lines) ? inv.lines : []
  return (
    <>
      <Section title="Partida">
        <KeyValue
          columns={2}
          labelWidth={110}
          items={compact([
            { label: 'Partida', value: mono(r.billing_item) },
            { label: 'Tipo', value: BILLING_TYPE_LABELS[String(r.type)] ?? str(r.type) },
            { label: 'Decisión', value: AR_BILLING_OUTCOME_CATALOG[r.expected as keyof typeof AR_BILLING_OUTCOME_CATALOG]?.label ?? str(r.expected) },
            { label: 'Sociedad', value: mono(r.company) },
            { label: 'Cliente', value: customer ? `${customer.id} · ${customer.name}` : str(r.customer) },
            { label: 'Contrato', value: mono(r.contract) },
          ])}
        />
      </Section>
      {inv && (
        <Section title="Factura">
          <KeyValue
            columns={2}
            labelWidth={110}
            items={compact([
              { label: 'Fecha', value: formatDate(inv.date) },
              { label: 'Vencimiento', value: formatDate(inv.due_date) },
              { label: 'Código IVA', value: mono(inv.tax_code) },
              { label: 'Base', value: money(inv.net, cur) },
              { label: 'IVA', value: money(inv.tax, cur) },
              num(inv.retention) ? { label: 'Retención', value: money(inv.retention, cur) } : null,
              ...(Array.isArray(inv.deductions) ? inv.deductions : []).map((d) => ({ label: `Deducción ${d.code ?? ''}`.trim(), value: money(d.amount, cur) })),
              { label: 'A cobrar', value: money(inv.payable, cur) },
              inv.face && { label: 'FACe (DIR3)', value: mono([inv.face.oficina_contable, inv.face.organo_gestor, inv.face.unidad_tramitadora].join(' · ')) },
            ])}
          />
        </Section>
      )}
      {lines.length > 0 && (
        <Section title="Líneas" count={lines.length}>
          <Table
            head={['Descripción', 'Cuenta', 'PEP · CC', 'Importe']}
            numeric={[3]}
            rows={lines.map((l) => [l.description, <AccountCell key="a" account={l.account} ctx={ctx} />, mono([l.wbs, l.cost_center].filter(Boolean).join(' · ')), money(l.amount, cur)])}
          />
        </Section>
      )}
    </>
  )
}

// ---------------------------------------------------------------- AR cash
function ArCashSummary({ ctx }: { ctx: ItemContext }) {
  const r = (ctx.rows[0] ?? {}) as Partial<ArCashRow>
  const cur = ctx.item.currency ?? 'EUR'
  const ref = findStatementLine(ctx.core, ctx.item.key)
  const customer = r.customer ? ctx.core.customers.find((c) => c.id === r.customer) : undefined
  const apps = Array.isArray(r.applications) ? r.applications : []
  const residuals = Array.isArray(r.residuals) ? r.residuals : []
  return (
    <>
      <Section title="Abono">
        <KeyValue
          columns={2}
          labelWidth={110}
          items={compact([
            { label: 'Línea', value: mono(ctx.item.key) },
            { label: 'Cuenta', value: mono(ref?.account) },
            { label: 'Fecha', value: ref ? formatDate(ref.line.booking_date) : null },
            { label: 'Importe', value: money(ref?.line.amount ?? ctx.item.amount, cur) },
            { label: 'Cliente', value: customer ? `${customer.id} · ${customer.name}` : r.customer ? String(r.customer) : 'No es un cliente' },
            { label: 'Resultado', value: outcomeEntry('ar_cash', ctx.item.outcome)?.label ?? ctx.item.outcome },
          ])}
        />
        {ref && <p className={styles.bankText}>{ref.line.text}</p>}
      </Section>
      {apps.length > 0 && (
        <Section title="Aplicaciones" count={apps.length}>
          <Table
            head={['Factura o pagaré', 'Pendiente', 'Aplicado']}
            numeric={[1, 2]}
            rows={apps.map((a) => {
              const invoice = a.invoice ? ctx.core.arInvoices.find((i) => i.id === a.invoice) : undefined
              return [mono(a.pagare ? `Pagaré ${a.pagare}` : a.invoice), money(invoice?.payable, cur), money(a.amount, cur)]
            })}
          />
        </Section>
      )}
      {residuals.length > 0 && (
        <Section title="Diferencias" count={residuals.length}>
          <Table
            head={['Tipo', 'Factura', 'Cuenta', 'Importe']}
            numeric={[3]}
            rows={residuals.map((x) => [AR_RESIDUAL_CATALOG[x.type as keyof typeof AR_RESIDUAL_CATALOG]?.label ?? x.type, mono(x.invoice), mono(x.account), money(x.amount, cur)])}
          />
        </Section>
      )}
    </>
  )
}

// ---------------------------------------------------------------- bank
function BankSummary({ ctx }: { ctx: ItemContext }) {
  const r = (ctx.rows[0] ?? {}) as Partial<BankRecRow> & Record<string, unknown>
  const account = ctx.item.key.split('/')[0]
  const bank = ctx.core.bankAccounts.find((b) => b.id === account)
  const cur = bank?.currency ?? ctx.item.currency ?? 'EUR'
  const banks = ctx.item.evidence.flatMap((e) => (e.kind === 'bank' ? [e.bank_line] : []))
  const books = ctx.item.evidence.flatMap((e) => (e.kind === 'journal' ? [e.book_line] : []))
  const category = BANK_CATEGORY_CATALOG[ctx.item.outcome as keyof typeof BANK_CATEGORY_CATALOG]
  const kind = banks.length && books.length ? `Casación ${matchShape(banks.length, books.length)}` : banks.length ? 'Sin casar en el extracto' : books.length ? 'Sin casar en libros' : 'Ajuste sin partida'
  return (
    <>
      <Section title="Esta partida">
        <KeyValue
          columns={2}
          labelWidth={110}
          items={compact([
            { label: 'Tipo', value: kind },
            { label: 'Categoría', value: category?.label ?? (ctx.item.outcome === 'MATCH' ? 'Casada' : ctx.item.outcome) },
            category && { label: 'Ajuste', value: category.adjustment ? 'Sí, contra la 572' : 'No' },
            { label: 'Importe', value: money(ctx.item.amount, cur) },
          ])}
        />
        {banks.length > 0 && (
          <Table
            head={['Línea del extracto', 'Fecha', 'Concepto', 'Importe']}
            numeric={[3]}
            rows={banks.map((b) => {
              const l = findStatementLine(ctx.core, b)?.line
              return [mono(b), l ? formatDate(l.booking_date) : null, l?.text ?? null, money(l?.amount, cur)]
            })}
          />
        )}
        {books.length > 0 && <Table head={['Apunte del libro']} rows={books.map((b) => [mono(b)])} />}
      </Section>
      <Section title="Cuenta">
        <KeyValue
          columns={2}
          labelWidth={110}
          items={compact([
            { label: 'Cuenta', value: mono(account) },
            { label: 'Sociedad', value: mono(r.company ?? bank?.company) },
            { label: 'Banco', value: bank?.bank ?? null },
            { label: 'IBAN', value: mono(bank?.iban ?? bank?.clabe) },
            { label: 'Cuenta contable', value: mono(bank?.gl_account ?? r.gl_account) },
            { label: 'Moneda', value: cur },
            num(r.statement_opening) !== null && { label: 'Saldo inicial', value: money(r.statement_opening, cur) },
            num(r.statement_closing) !== null && { label: 'Saldo final', value: money(r.statement_closing, cur) },
            { label: 'Casaciones', value: String(Array.isArray(r.matches) ? r.matches.length : 0) },
            {
              label: 'Sin casar',
              value: `${Array.isArray(r.unmatched_bank) ? r.unmatched_bank.length : 0} extracto · ${Array.isArray(r.unmatched_book) ? r.unmatched_book.length : 0} libros`,
            },
            { label: 'Ajustes', value: String(Array.isArray(r.adjustments) ? r.adjustments.length : 0) },
          ])}
        />
      </Section>
    </>
  )
}

// ---------------------------------------------------------------- IC
function IcSummary({ ctx }: { ctx: ItemContext }) {
  const r = (ctx.rows[0] ?? {}) as Partial<IcRow> & Record<string, unknown>
  const cur = ctx.item.currency ?? 'EUR'
  return (
    <Section title="Diferencia">
      <KeyValue
        labelWidth={110}
        items={compact([
          { label: 'Pareja', value: mono(Array.isArray(r.pair) ? r.pair.join(' – ') : ctx.item.key.split('/')[0]) },
          { label: 'Causa', value: IC_CAUSE_CATALOG[r.cause as keyof typeof IC_CAUSE_CATALOG]?.label ?? str(r.cause) },
          { label: 'Importe', value: money(r.amount, cur) },
          { label: 'Responsable', value: mono(r.responsible) },
          str(r.account) && { label: 'Cuentas', value: mono(r.account) },
          str(r.detail) && { label: 'Detalle', value: String(r.detail) },
          { label: 'Ajuste', value: Array.isArray(r.adjustment) && r.adjustment.length ? `${r.adjustment.length} líneas` : 'Sin ajuste' },
        ])}
      />
    </Section>
  )
}

// ---------------------------------------------------------------- close
const CLOSE_LABELS: Record<string, string> = {
  type: 'Tipo',
  company: 'Sociedad',
  vendor: 'Proveedor',
  customer: 'Cliente',
  invoice: 'Factura',
  item: 'Partida',
  billing_item: 'Partida de facturación',
  amount: 'Importe',
  period: 'Periodo',
  currency: 'Moneda',
  foreign: 'Importe en divisa',
  rate: 'Tipo de cierre',
  target: 'Provisión necesaria',
  previous: 'Provisión anterior',
}

function CloseSummary({ ctx }: { ctx: ItemContext }) {
  const cur = ctx.item.currency ?? 'EUR'
  return (
    <>
      {ctx.rows.map((r, i) => (
        <Section key={i} title={ctx.rows.length > 1 ? `Fila ${i + 1}` : 'Partida de cierre'}>
          <KeyValue
            columns={2}
            labelWidth={120}
            items={compact(
              Object.entries(r)
                .filter(([k, v]) => k !== 'journal_entry' && (v === null || typeof v !== 'object' || Array.isArray(v)))
                .map(([k, v]) => ({
                  label: CLOSE_LABELS[k] ?? k,
                  value:
                    k === 'amount' || k === 'target' || k === 'previous'
                      ? money(v, cur)
                      : k === 'foreign'
                        ? money(v, str(r.currency) ?? cur)
                        : k === 'type'
                          ? (outcomeEntry('close', String(v))?.label ?? String(v))
                          : Array.isArray(v)
                            ? v.map(String).join(' – ')
                            : v === null
                              ? null
                              : typeof v === 'string'
                                ? mono(v)
                                : String(v),
                })),
            )}
          />
        </Section>
      ))}
    </>
  )
}
