// Detail pages of a vendor, a customer and a project, with everything that points at them.
import { useMemo } from 'react'
import { useNavigate, useParams } from 'react-router'
import { BookOpen } from 'lucide-react'
import { Amount, Badge, ButtonLink, DataTable, Mono, Page, Section, type Column } from '@/components'
import type { ApDocumentLogEntry, ApInvoice, ArInvoice, DatasetCore, OpenItem, PromissoryNote, PurchaseOrder, SalesContract } from '@/domain/types'
import { formatDate, formatPercent } from '@/lib/format'
import { DetailHeader, Facts, ItemLinks, NotFound, TextLink, tableHeight, useApi, useCompanyCurrency, useRunItems } from './common'
import { customerLinks, dataPath, itemsCiting, vendorLinks } from './model'
import styles from './DataExplorer.module.css'

const dash = <span className={styles.muted}>—</span>
const monoOr = (v: string | null | undefined) => (v ? <Mono>{v}</Mono> : dash)
const accountLink = (a: string | null | undefined) => (a ? <TextLink to={dataPath.account(a)} mono>{a}</TextLink> : dash)
const entryLink = (id: string | null | undefined) => (id ? <TextLink to={dataPath.entry(id)} mono>{id}</TextLink> : dash)

function RunItems({ file, id }: { file: string; id: string }) {
  const run = useRunItems()
  const items = useMemo(() => (run ? itemsCiting(run.items, file, id) : []), [run, file, id])
  return (
    <Section title="Partidas de este cierre" count={run ? items.length : undefined} description="Partidas de la ejecución activa cuya evidencia cita esta ficha.">
      <ItemLinks items={items} empty={run ? 'Ninguna partida de la ejecución activa cita esta ficha.' : 'Abre una ejecución para ver las partidas que la citan.'} />
    </Section>
  )
}

// ---------------------------------------------------------------- vendor

export function VendorPage() {
  const { id = '' } = useParams()
  const { core } = useApi()
  const vendor = core.vendors.find((v) => v.id === id)
  const links = useMemo(() => vendorLinks(core, id), [core, id])
  if (!vendor) return <NotFound what={`No hay ningún proveedor ${id}`} />
  const iban = vendor.bank.iban ?? vendor.bank.clabe ?? vendor.bank.account ?? null
  return (
    <Page>
      <DetailHeader
        crumbs={[{ label: 'Datos', to: '/datos' }, { label: 'Proveedores', to: '/datos/maestros/proveedores' }, { label: vendor.id }]}
        title={vendor.name}
        subtitle={<Mono>{vendor.id}</Mono>}
        actions={
          <ButtonLink to={dataPath.journal({ text: vendor.id })} leadingIcon={<BookOpen />}>
            Sus apuntes en el diario
          </ButtonLink>
        }
      />
      <Facts
        items={[
          { label: 'NIF', value: monoOr(vendor.tax_id) },
          { label: 'NIF-IVA', value: monoOr(vendor.vat_id) },
          { label: 'País y moneda', value: `${vendor.country} · ${vendor.currency}` },
          { label: 'Tipo', value: vendor.archetype },
          { label: 'Dirección', value: [vendor.address.street, vendor.address.postal_code, vendor.address.city].filter(Boolean).join(', ') },
          { label: 'Correo', value: vendor.email },
          { label: 'Cuenta de pago', value: monoOr(iban) },
          {
            label: 'Cuentas anteriores',
            value: vendor.bank_history.length
              ? vendor.bank_history.map((h) => (
                  <span key={h.iban} className={styles.block}>
                    <Mono>{h.iban}</Mono> <span className={styles.muted}>hasta {formatDate(h.valid_to)}</span>
                  </span>
                ))
              : dash,
          },
          { label: 'Forma y plazo de pago', value: `${vendor.payment_method} · ${vendor.payment_terms_days} días` },
          { label: 'Cuenta asociada', value: accountLink(vendor.reconciliation_account) },
          { label: 'Cuenta de gasto', value: accountLink(vendor.default_gl_account) },
          { label: 'IVA por defecto', value: monoOr(vendor.default_tax_code) },
          { label: 'Retención', value: monoOr(vendor.withholding) },
          { label: 'Pedido obligatorio', value: vendor.po_required ? 'Sí' : 'No' },
          { label: 'Sociedades', value: vendor.companies.map((c) => <Mono key={c}>{c} </Mono>) },
          { label: 'Alta', value: formatDate(vendor.created_on) },
          ...(vendor.intercompany ? [{ label: 'Intragrupo', value: <Mono>{vendor.intercompany}</Mono> }] : []),
          ...(vendor.guarantee_retention_bp ? [{ label: 'Retención de garantía', value: formatPercent(vendor.guarantee_retention_bp / 10000) }] : []),
          ...(vendor.alternative_payee
            ? [{ label: 'Cesionario', value: `${vendor.alternative_payee.name} (${vendor.alternative_payee.type}) desde ${formatDate(vendor.alternative_payee.from_date)}` }]
            : []),
          ...(vendor.garnishments?.length
            ? [{ label: 'Embargos', value: vendor.garnishments.map((g) => <span key={g.ref} className={styles.block}><Mono>{g.ref}</Mono> <Amount cents={g.amount} currency={vendor.currency} /> desde {formatDate(g.from_date)}</span>) }]
            : []),
          ...(links.certificates.length
            ? [{ label: 'Certificado art. 43', value: links.certificates.map((c) => `${c.reference}, válido hasta ${formatDate(c.valid_until)}`).join(' · ') }]
            : []),
        ]}
      />
      <RunItems file="erp/vendors.jsonl" id={vendor.id} />
      <ApInvoices core={core} rows={links.invoices} />
      <DocumentLog rows={links.documentLog} />
      <PurchaseOrders core={core} rows={links.purchaseOrders} />
    </Page>
  )
}

function ApInvoices({ core, rows }: { core: DatasetCore; rows: ApInvoice[] }) {
  const currency = useCompanyCurrency(core)
  const columns = useMemo<Column<ApInvoice>[]>(
    () => [
      { id: 'doc', header: 'Documento', width: 110, cell: (i) => <Mono>{i.doc_id}</Mono>, sortValue: (i) => i.doc_id },
      { id: 'number', header: 'Número', width: 'minmax(120px, 1fr)', cell: (i) => <Mono>{i.number}</Mono> },
      { id: 'company', header: 'Sociedad', width: 80, cell: (i) => <Mono>{i.company}</Mono> },
      { id: 'kind', header: 'Tipo', width: 110, cell: (i) => i.kind },
      { id: 'issue', header: 'Emisión', width: 110, cell: (i) => formatDate(i.issue_date), sortValue: (i) => i.issue_date },
      { id: 'gross', header: 'Total', width: 140, align: 'right', cell: (i) => <Amount cents={i.gross} currency={i.currency || currency(i.company)} />, sortValue: (i) => i.gross },
      { id: 'payable', header: 'A pagar', width: 140, align: 'right', cell: (i) => <Amount cents={i.payable} currency={i.currency || currency(i.company)} />, sortValue: (i) => i.payable },
      { id: 'decision', header: 'Decisión', width: 140, cell: (i) => <Mono>{i.decision}</Mono> },
      { id: 'je', header: 'Asiento', width: 150, cell: (i) => entryLink(i.journal_entry) },
    ],
    [currency],
  )
  return (
    <Section title="Facturas registradas" count={rows.length} description="Histórico de facturas contabilizadas (erp/ap_invoices.jsonl).">
      <DataTable aria-label="Facturas registradas" rows={rows} columns={columns} getRowId={(i) => i.doc_id} height={tableHeight(rows.length)} />
    </Section>
  )
}

function DocumentLog({ rows }: { rows: ApDocumentLogEntry[] }) {
  const columns = useMemo<Column<ApDocumentLogEntry>[]>(
    () => [
      { id: 'doc', header: 'Documento', width: 110, cell: (d) => <Mono>{d.doc_id}</Mono>, sortValue: (d) => d.doc_id },
      { id: 'received', header: 'Recibido', width: 110, cell: (d) => formatDate(d.received_on), sortValue: (d) => d.received_on },
      { id: 'kind', header: 'Tipo', width: 120, cell: (d) => d.kind },
      { id: 'number', header: 'Número', width: 'minmax(120px, 1fr)', cell: (d) => monoOr(d.number) },
      { id: 'decision', header: 'Decisión', width: 140, cell: (d) => <Mono>{d.decision}</Mono> },
      { id: 'reasons', header: 'Motivos', width: 'minmax(160px, 1.5fr)', cell: (d) => (d.reasons.length ? <Mono>{d.reasons.join(', ')}</Mono> : dash) },
      { id: 'dup', header: 'Duplicado de', width: 120, cell: (d) => monoOr(d.duplicate_of) },
      { id: 'je', header: 'Asiento', width: 150, cell: (d) => entryLink(d.journal_entry) },
    ],
    [],
  )
  return (
    <Section title="Histórico de documentos" count={rows.length} description="Decisiones sobre documentos de meses anteriores (erp/ap_document_log.jsonl).">
      <DataTable aria-label="Histórico de documentos" rows={rows} columns={columns} getRowId={(d) => d.doc_id} height={tableHeight(rows.length)} />
    </Section>
  )
}

const poTotal = (p: PurchaseOrder) => p.items.reduce((s, i) => s + Math.round((i.quantity_milli * i.unit_price) / 1000), 0)

function PurchaseOrders({ core, rows }: { core: DatasetCore; rows: PurchaseOrder[] }) {
  const currency = useCompanyCurrency(core)
  const columns = useMemo<Column<PurchaseOrder>[]>(
    () => [
      { id: 'id', header: 'Pedido', width: 130, cell: (p) => <Mono>{p.id}</Mono>, sortValue: (p) => p.id },
      { id: 'company', header: 'Sociedad', width: 80, cell: (p) => <Mono>{p.company}</Mono> },
      { id: 'created', header: 'Fecha', width: 110, cell: (p) => formatDate(p.created_on), sortValue: (p) => p.created_on },
      { id: 'type', header: 'Tipo', width: 90, cell: (p) => p.type },
      { id: 'project', header: 'Proyecto', width: 110, cell: (p) => (p.project ? <TextLink to={dataPath.project(p.project)} mono>{p.project}</TextLink> : dash) },
      { id: 'text', header: 'Texto', width: 'minmax(200px, 2fr)', cell: (p) => p.text },
      { id: 'lines', header: 'Líneas', width: 70, align: 'right', cell: (p) => p.items.length },
      { id: 'total', header: 'Importe', width: 150, align: 'right', cell: (p) => <Amount cents={poTotal(p)} currency={p.currency || currency(p.company)} />, sortValue: poTotal },
    ],
    [currency],
  )
  return (
    <Section title="Pedidos de compra" count={rows.length}>
      <DataTable aria-label="Pedidos de compra" rows={rows} columns={columns} getRowId={(p) => p.id} height={tableHeight(rows.length)} />
    </Section>
  )
}

// ---------------------------------------------------------------- customer

export function CustomerPage() {
  const { id = '' } = useParams()
  const { core } = useApi()
  const customer = core.customers.find((c) => c.id === id)
  const links = useMemo(() => customerLinks(core, id), [core, id])
  if (!customer) return <NotFound what={`No hay ningún cliente ${id}`} />
  return (
    <Page>
      <DetailHeader
        crumbs={[{ label: 'Datos', to: '/datos' }, { label: 'Clientes', to: '/datos/maestros/clientes' }, { label: customer.id }]}
        title={customer.name}
        subtitle={<Mono>{customer.id}</Mono>}
        actions={
          <ButtonLink to={dataPath.journal({ text: customer.id })} leadingIcon={<BookOpen />}>
            Sus apuntes en el diario
          </ButtonLink>
        }
      />
      <Facts
        items={[
          { label: 'NIF', value: monoOr(customer.tax_id) },
          { label: 'Tipo', value: customer.kind },
          { label: 'País y moneda', value: `${customer.country} · ${customer.currency}` },
          { label: 'Dirección', value: [customer.address.street, customer.address.postal_code, customer.address.city].filter(Boolean).join(', ') },
          { label: 'IBAN', value: monoOr(customer.iban) },
          { label: 'Mandato SEPA', value: monoOr(customer.mandate) },
          ...(customer.dir3
            ? [{ label: 'DIR3 (FACe)', value: <Mono>{`${customer.dir3.oficina_contable} · ${customer.dir3.organo_gestor} · ${customer.dir3.unidad_tramitadora}`}</Mono> }]
            : []),
          ...(customer.group ? [{ label: 'Intragrupo', value: <Mono>{customer.group}</Mono> }] : []),
          ...(customer.insolvency
            ? [
                {
                  label: 'Concurso',
                  value: (
                    <Badge tone="danger">
                      {customer.insolvency.proceeding} · {customer.insolvency.court} · {formatDate(customer.insolvency.declared_on)}
                    </Badge>
                  ),
                },
              ]
            : []),
        ]}
      />
      <RunItems file="erp/customers.jsonl" id={customer.id} />
      <Contracts core={core} rows={links.contracts} />
      <ArInvoices core={core} rows={links.invoices} />
      <OpenItems core={core} rows={links.openItems} />
      {links.promissoryNotes.length > 0 && <PromissoryNotes core={core} rows={links.promissoryNotes} />}
    </Page>
  )
}

function Contracts({ core, rows }: { core: DatasetCore; rows: SalesContract[] }) {
  const currency = useCompanyCurrency(core)
  const columns = useMemo<Column<SalesContract>[]>(
    () => [
      { id: 'id', header: 'Contrato', width: 'minmax(160px, 1fr)', cell: (k) => <Mono>{k.id}</Mono>, sortValue: (k) => k.id },
      { id: 'company', header: 'Sociedad', width: 80, cell: (k) => <Mono>{k.company}</Mono> },
      { id: 'kind', header: 'Tipo', width: 140, cell: (k) => k.kind },
      { id: 'project', header: 'Proyecto', width: 110, cell: (k) => (k.project ? <TextLink to={dataPath.project(k.project)} mono>{k.project}</TextLink> : dash) },
      { id: 'tax', header: 'IVA', width: 70, cell: (k) => <Mono>{k.tax}</Mono> },
      { id: 'value', header: 'Importe', width: 150, align: 'right', cell: (k) => <Amount cents={k.value ?? k.fee ?? null} currency={currency(k.company)} /> },
      { id: 'period', header: 'Vigencia', width: 200, cell: (k) => `${formatDate(k.start)} – ${formatDate(k.end)}` },
    ],
    [currency],
  )
  return (
    <Section title="Contratos" count={rows.length}>
      <DataTable aria-label="Contratos" rows={rows} columns={columns} getRowId={(k) => k.id} height={tableHeight(rows.length)} />
    </Section>
  )
}

function ArInvoices({ core, rows }: { core: DatasetCore; rows: ArInvoice[] }) {
  const currency = useCompanyCurrency(core)
  const columns = useMemo<Column<ArInvoice>[]>(
    () => [
      { id: 'id', header: 'Factura', width: 130, cell: (i) => <Mono>{i.id}</Mono>, sortValue: (i) => i.id },
      { id: 'contract', header: 'Contrato', width: 'minmax(150px, 1fr)', cell: (i) => <Mono>{i.contract}</Mono> },
      { id: 'date', header: 'Fecha', width: 110, cell: (i) => formatDate(i.date), sortValue: (i) => i.date },
      { id: 'due', header: 'Vencimiento', width: 110, cell: (i) => formatDate(i.due_date), sortValue: (i) => i.due_date },
      { id: 'gross', header: 'Total', width: 140, align: 'right', cell: (i) => <Amount cents={i.gross} currency={i.currency || currency(i.company)} />, sortValue: (i) => i.gross },
      { id: 'factored', header: 'Cedida', width: 70, cell: (i) => (i.factored ? 'Sí' : 'No') },
      { id: 'je', header: 'Asiento', width: 150, cell: (i) => entryLink(i.journal_entry) },
    ],
    [currency],
  )
  return (
    <Section title="Facturas emitidas" count={rows.length} description="erp/ar_invoices.jsonl">
      <DataTable aria-label="Facturas emitidas" rows={rows} columns={columns} getRowId={(i) => i.id} height={tableHeight(rows.length)} />
    </Section>
  )
}

function OpenItems({ core, rows }: { core: DatasetCore; rows: OpenItem[] }) {
  const currency = useCompanyCurrency(core)
  const columns = useMemo<Column<OpenItem>[]>(
    () => [
      { id: 'assignment', header: 'Asignación', width: 'minmax(160px, 1fr)', cell: (o) => <Mono>{o.assignment}</Mono>, sortValue: (o) => o.assignment },
      { id: 'company', header: 'Sociedad', width: 80, cell: (o) => <Mono>{o.company}</Mono> },
      { id: 'account', header: 'Cuenta', width: 120, cell: (o) => accountLink(o.account) },
      { id: 'balance', header: 'Saldo', width: 150, align: 'right', cell: (o) => <Amount cents={o.balance} currency={currency(o.company)} />, sortValue: (o) => o.balance },
    ],
    [currency],
  )
  return (
    <Section title="Partidas abiertas" count={rows.length} description="Saldo pendiente al inicio del mes (erp/open_items.jsonl).">
      <DataTable aria-label="Partidas abiertas" rows={rows} columns={columns} getRowId={(o) => `${o.company}/${o.account}/${o.assignment}`} height={tableHeight(rows.length)} />
    </Section>
  )
}

function PromissoryNotes({ core, rows }: { core: DatasetCore; rows: PromissoryNote[] }) {
  const currency = useCompanyCurrency(core)
  const columns = useMemo<Column<PromissoryNote>[]>(
    () => [
      { id: 'number', header: 'Pagaré', width: 'minmax(140px, 1fr)', cell: (p) => <Mono>{p.number}</Mono> },
      { id: 'received', header: 'Recibido', width: 110, cell: (p) => formatDate(p.received_on) },
      { id: 'maturity', header: 'Vencimiento', width: 110, cell: (p) => formatDate(p.maturity), sortValue: (p) => p.maturity },
      { id: 'amount', header: 'Importe', width: 150, align: 'right', cell: (p) => <Amount cents={p.amount} currency={currency(p.company)} /> },
      { id: 'je', header: 'Asiento', width: 150, cell: (p) => entryLink(p.journal_entry) },
    ],
    [currency],
  )
  return (
    <Section title="Pagarés" count={rows.length}>
      <DataTable aria-label="Pagarés" rows={rows} columns={columns} getRowId={(p) => p.number} height={tableHeight(rows.length)} />
    </Section>
  )
}

// ---------------------------------------------------------------- project

export function ProjectPage() {
  const { id = '' } = useParams()
  const { core } = useApi()
  const navigate = useNavigate()
  const currency = useCompanyCurrency(core)
  const project = core.projects.find((p) => p.id === id)
  const contracts = useMemo(() => core.salesContracts.filter((k) => k.project === id), [core, id])
  const orders = useMemo(() => core.purchaseOrders.filter((p) => p.project === id), [core, id])
  const wbsColumns = useMemo<Column<{ id: string; desc: string; sub: string }>[]>(
    () => [
      { id: 'id', header: 'PEP', width: 'minmax(180px, 1fr)', cell: (w) => <Mono>{w.id}</Mono>, sortValue: (w) => w.id },
      { id: 'desc', header: 'Descripción', width: 'minmax(220px, 2fr)', cell: (w) => w.desc },
      { id: 'sub', header: 'Subpartida', width: 140, cell: (w) => w.sub },
    ],
    [],
  )
  if (!project) return <NotFound what={`No hay ningún proyecto ${id}`} />
  return (
    <Page>
      <DetailHeader
        crumbs={[{ label: 'Datos', to: '/datos' }, { label: 'Proyectos', to: '/datos/maestros/proyectos' }, { label: project.id }]}
        title={project.name}
        subtitle={<Mono>{project.id}</Mono>}
      />
      <Facts
        items={[
          { label: 'Sociedad', value: <Mono>{project.company}</Mono> },
          { label: 'Municipio', value: project.town },
          { label: 'Tipo', value: project.kind },
          { label: 'Obra pública', value: project.public_works ? 'Sí' : 'No' },
          { label: 'Inicio', value: formatDate(project.start) },
          { label: 'Fin previsto', value: formatDate(project.planned_end) },
          { label: 'Presupuesto de coste', value: <Amount cents={project.budget_cost} currency={currency(project.company)} /> },
        ]}
      />
      <Section title="Elementos PEP" count={project.wbs.length}>
        <DataTable aria-label="Elementos PEP" rows={project.wbs} columns={wbsColumns} getRowId={(w) => w.id} height={tableHeight(project.wbs.length)} />
      </Section>
      <Section title="Contratos de venta" count={contracts.length}>
        {contracts.length ? (
          <ul className={styles.linkList}>
            {contracts.map((k) => (
              <li key={k.id}>
                <button type="button" className={styles.itemRow} onClick={() => navigate(dataPath.customer(k.customer))}>
                  <Mono>{k.id}</Mono>
                  <span className={styles.itemTitle}>{core.customers.find((c) => c.id === k.customer)?.name ?? k.customer}</span>
                  <Amount cents={k.value ?? k.fee ?? null} currency={currency(k.company)} />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.muted}>Ningún contrato de venta cita este proyecto.</p>
        )}
      </Section>
      <PurchaseOrders core={core} rows={orders} />
    </Page>
  )
}
