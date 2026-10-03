// `/datos` and `/datos/maestros/:kind`: one table per master file of erp/.
import { useMemo, type ReactNode } from 'react'
import { useNavigate, useParams } from 'react-router'
import { Amount, Badge, DataTable, Mono, Page, PageHeader, type Column } from '@/components'
import type { BankAccount, ChartAccount, CostCenter, Customer, DatasetCore, Project, SalesContract, Vendor } from '@/domain/types'
import { formatNumber, formatPercent } from '@/lib/format'
import { NotFound, SectionTabs, TextLink, useApi, useCompanyCurrency } from './common'
import { dataPath } from './model'
import styles from './DataExplorer.module.css'

const KINDS = [
  { id: 'proveedores', label: 'Proveedores' },
  { id: 'clientes', label: 'Clientes' },
  { id: 'contratos', label: 'Contratos' },
  { id: 'proyectos', label: 'Proyectos' },
  { id: 'cuentas', label: 'Plan de cuentas' },
  { id: 'impuestos', label: 'Impuestos' },
  { id: 'centros', label: 'Centros de coste' },
  { id: 'bancos', label: 'Cuentas bancarias' },
] as const
type Kind = (typeof KINDS)[number]['id']

const isKind = (k: string | undefined): k is Kind => KINDS.some((x) => x.id === k)

export function MastersPage() {
  const { kind = 'proveedores' } = useParams()
  const navigate = useNavigate()
  const { core } = useApi()
  if (!isKind(kind)) return <NotFound />
  const counts: Record<Kind, number> = {
    proveedores: core.vendors.length,
    clientes: core.customers.length,
    contratos: core.salesContracts.length,
    proyectos: core.projects.length,
    cuentas: core.chartOfAccounts.length,
    impuestos: taxRows(core).length,
    centros: core.costCenters.length,
    bancos: core.bankAccounts.length,
  }
  return (
    <Page fill>
      <PageHeader title="Datos" subtitle="Lo que contienen las entradas del mes: maestros, diario, documentos y extractos." filters={<SectionTabs />} />
      <nav className={styles.kinds} aria-label="Maestros">
        {KINDS.map((k) => (
          <button key={k.id} type="button" className={styles.kind} aria-current={k.id === kind ? 'page' : undefined} onClick={() => navigate(`/datos/maestros/${k.id}`)}>
            {k.label}
            <span className="tabular">{formatNumber(counts[k.id])}</span>
          </button>
        ))}
      </nav>
      <MasterTable kind={kind} core={core} />
    </Page>
  )
}

function MasterTable({ kind, core }: { kind: Kind; core: DatasetCore }) {
  switch (kind) {
    case 'proveedores':
      return <Vendors core={core} />
    case 'clientes':
      return <Customers core={core} />
    case 'contratos':
      return <Contracts core={core} />
    case 'proyectos':
      return <Projects core={core} />
    case 'cuentas':
      return <Accounts core={core} />
    case 'impuestos':
      return <Taxes core={core} />
    case 'centros':
      return <CostCenters core={core} />
    case 'bancos':
      return <BankAccounts core={core} />
  }
}

const mono = (v: ReactNode) => (v == null || v === '' ? <span className={styles.muted}>—</span> : <Mono>{v}</Mono>)

function Vendors({ core }: { core: DatasetCore }) {
  const navigate = useNavigate()
  const columns = useMemo<Column<Vendor>[]>(
    () => [
      { id: 'id', header: 'Proveedor', width: 110, cell: (v) => <Mono>{v.id}</Mono>, sortValue: (v) => v.id },
      { id: 'name', header: 'Nombre', width: 'minmax(220px, 2fr)', cell: (v) => v.name, sortValue: (v) => v.name },
      { id: 'tax', header: 'NIF', width: 120, cell: (v) => mono(v.tax_id) },
      { id: 'country', header: 'País', width: 60, cell: (v) => v.country, sortValue: (v) => v.country },
      { id: 'archetype', header: 'Tipo', width: 120, cell: (v) => v.archetype, sortValue: (v) => v.archetype },
      { id: 'iban', header: 'Cuenta de pago', width: 'minmax(200px, 1fr)', cell: (v) => mono(v.bank.iban ?? v.bank.clabe ?? v.bank.account) },
      { id: 'terms', header: 'Plazo', width: 70, align: 'right', cell: (v) => `${v.payment_terms_days} d`, sortValue: (v) => v.payment_terms_days },
      { id: 'flags', header: 'Avisos', width: 150, cell: (v) => <VendorFlags v={v} /> },
    ],
    [],
  )
  return <DataTable aria-label="Proveedores" rows={core.vendors} columns={columns} getRowId={(v) => v.id} onOpen={(v) => navigate(dataPath.vendor(v.id))} globalKeys />
}

function VendorFlags({ v }: { v: Vendor }) {
  return (
    <span className={styles.flags}>
      {v.intercompany && <Badge tone="info">Intragrupo</Badge>}
      {v.bank_history.length > 0 && <Badge tone="warn">IBAN cambiado</Badge>}
      {v.alternative_payee && <Badge tone="warn">Cesión</Badge>}
      {v.garnishments?.length ? <Badge tone="danger">Embargo</Badge> : null}
    </span>
  )
}

function Customers({ core }: { core: DatasetCore }) {
  const navigate = useNavigate()
  const columns = useMemo<Column<Customer>[]>(
    () => [
      { id: 'id', header: 'Cliente', width: 110, cell: (c) => <Mono>{c.id}</Mono>, sortValue: (c) => c.id },
      { id: 'name', header: 'Nombre', width: 'minmax(220px, 2fr)', cell: (c) => c.name, sortValue: (c) => c.name },
      { id: 'tax', header: 'NIF', width: 120, cell: (c) => mono(c.tax_id) },
      { id: 'kind', header: 'Tipo', width: 140, cell: (c) => c.kind, sortValue: (c) => c.kind },
      { id: 'country', header: 'País', width: 60, cell: (c) => c.country },
      { id: 'iban', header: 'IBAN', width: 'minmax(200px, 1fr)', cell: (c) => mono(c.iban) },
      {
        id: 'flags',
        header: 'Avisos',
        width: 170,
        cell: (c) => (
          <span className={styles.flags}>
            {c.dir3 && <Badge tone="info">FACe</Badge>}
            {c.group && <Badge tone="info">Intragrupo</Badge>}
            {c.insolvency && <Badge tone="danger">Concurso</Badge>}
          </span>
        ),
      },
    ],
    [],
  )
  return <DataTable aria-label="Clientes" rows={core.customers} columns={columns} getRowId={(c) => c.id} onOpen={(c) => navigate(dataPath.customer(c.id))} globalKeys />
}

function Contracts({ core }: { core: DatasetCore }) {
  const navigate = useNavigate()
  const currency = useCompanyCurrency(core)
  const customers = useMemo(() => new Map(core.customers.map((c) => [c.id, c.name])), [core.customers])
  const columns = useMemo<Column<SalesContract>[]>(
    () => [
      { id: 'id', header: 'Contrato', width: 160, cell: (k) => <Mono>{k.id}</Mono>, sortValue: (k) => k.id },
      { id: 'company', header: 'Sociedad', width: 80, cell: (k) => <Mono>{k.company}</Mono>, sortValue: (k) => k.company },
      { id: 'customer', header: 'Cliente', width: 'minmax(200px, 2fr)', cell: (k) => customers.get(k.customer) ?? k.customer, sortValue: (k) => customers.get(k.customer) ?? k.customer },
      { id: 'kind', header: 'Tipo', width: 140, cell: (k) => k.kind, sortValue: (k) => k.kind },
      { id: 'project', header: 'Proyecto', width: 110, cell: (k) => (k.project ? <TextLink to={dataPath.project(k.project)} mono>{k.project}</TextLink> : mono(null)) },
      { id: 'value', header: 'Importe', width: 150, align: 'right', cell: (k) => <Amount cents={k.value ?? k.fee ?? null} currency={currency(k.company)} />, sortValue: (k) => k.value ?? k.fee },
      { id: 'retention', header: 'Retención', width: 90, align: 'right', cell: (k) => (k.retention_bp ? formatPercent(k.retention_bp / 10000) : '—') },
      { id: 'terms', header: 'Plazo', width: 70, align: 'right', cell: (k) => `${k.terms_days} d` },
    ],
    [currency, customers],
  )
  return <DataTable aria-label="Contratos" rows={core.salesContracts} columns={columns} getRowId={(k) => k.id} onOpen={(k) => navigate(dataPath.customer(k.customer))} globalKeys />
}

function Projects({ core }: { core: DatasetCore }) {
  const navigate = useNavigate()
  const currency = useCompanyCurrency(core)
  const columns = useMemo<Column<Project>[]>(
    () => [
      { id: 'id', header: 'Proyecto', width: 110, cell: (p) => <Mono>{p.id}</Mono>, sortValue: (p) => p.id },
      { id: 'company', header: 'Sociedad', width: 80, cell: (p) => <Mono>{p.company}</Mono>, sortValue: (p) => p.company },
      { id: 'name', header: 'Nombre', width: 'minmax(220px, 2fr)', cell: (p) => p.name, sortValue: (p) => p.name },
      { id: 'town', header: 'Municipio', width: 150, cell: (p) => p.town },
      { id: 'kind', header: 'Tipo', width: 130, cell: (p) => p.kind },
      { id: 'public', header: 'Obra pública', width: 100, cell: (p) => (p.public_works ? 'Sí' : 'No') },
      { id: 'budget', header: 'Presupuesto de coste', width: 170, align: 'right', cell: (p) => <Amount cents={p.budget_cost} currency={currency(p.company)} />, sortValue: (p) => p.budget_cost },
      { id: 'wbs', header: 'PEP', width: 60, align: 'right', cell: (p) => p.wbs.length },
    ],
    [currency],
  )
  return <DataTable aria-label="Proyectos" rows={core.projects} columns={columns} getRowId={(p) => p.id} onOpen={(p) => navigate(dataPath.project(p.id))} globalKeys />
}

function Accounts({ core }: { core: DatasetCore }) {
  const navigate = useNavigate()
  const columns = useMemo<Column<ChartAccount>[]>(
    () => [
      { id: 'account', header: 'Cuenta', width: 120, cell: (a) => <Mono>{a.account}</Mono>, sortValue: (a) => a.account },
      { id: 'description', header: 'Descripción', width: 'minmax(260px, 3fr)', cell: (a) => a.description, sortValue: (a) => a.description },
      { id: 'type', header: 'Tipo', width: 140, cell: (a) => a.type, sortValue: (a) => a.type },
      { id: 'open', header: 'Partidas abiertas', width: 140, cell: (a) => (a.open_items ? 'Sí' : 'No') },
    ],
    [],
  )
  return (
    <DataTable aria-label="Plan de cuentas" rows={core.chartOfAccounts} columns={columns} getRowId={(a) => a.account} onOpen={(a) => navigate(dataPath.account(a.account))} globalKeys />
  )
}

interface TaxRow {
  id: string
  group: string
  code: string
  /** Basis points, as in tax_codes.json (2100 = 21 %). */
  rate: number
  desc: string
  detail: string
  account: string | null
}

function taxRows(core: DatasetCore): TaxRow[] {
  const { tax_codes, withholdings, customer_deductions } = core.taxCodes
  return [
    ...Object.entries(tax_codes).map(([code, t]) => ({ id: `t:${code}`, group: 'Impuestos indirectos', code, rate: t.rate, desc: t.desc, detail: `${t.country} · ${t.kind}`, account: null })),
    ...Object.entries(withholdings).map(([code, w]) => ({ id: `w:${code}`, group: 'Retenciones', code, rate: w.rate, desc: w.desc, detail: `Modelo ${w.model}`, account: w.account })),
    ...Object.entries(customer_deductions).map(([code, d]) => ({ id: `d:${code}`, group: 'Deducciones de cliente', code, rate: d.rate, desc: d.desc, detail: '', account: d.account })),
  ]
}

const TAX_GROUPS = ['Impuestos indirectos', 'Retenciones', 'Deducciones de cliente']

function Taxes({ core }: { core: DatasetCore }) {
  const rows = useMemo(() => taxRows(core), [core])
  const columns = useMemo<Column<TaxRow>[]>(
    () => [
      { id: 'code', header: 'Código', width: 110, cell: (t) => <Mono>{t.code}</Mono>, sortValue: (t) => t.code },
      { id: 'desc', header: 'Descripción', width: 'minmax(260px, 3fr)', cell: (t) => t.desc },
      { id: 'detail', header: 'Detalle', width: 160, cell: (t) => t.detail },
      { id: 'rate', header: 'Tipo', width: 90, align: 'right', cell: (t) => formatPercent(t.rate / 10000), sortValue: (t) => t.rate },
      { id: 'account', header: 'Cuenta', width: 120, cell: (t) => (t.account ? <TextLink to={dataPath.account(t.account)} mono>{t.account}</TextLink> : mono(null)) },
    ],
    [],
  )
  return <DataTable aria-label="Impuestos" rows={rows} columns={columns} getRowId={(t) => t.id} groupBy={(t) => t.group} groupOrder={TAX_GROUPS} globalKeys />
}

function CostCenters({ core }: { core: DatasetCore }) {
  const columns = useMemo<Column<CostCenter>[]>(
    () => [
      { id: 'id', header: 'Centro de coste', width: 160, cell: (c) => <Mono>{c.id}</Mono>, sortValue: (c) => c.id },
      { id: 'company', header: 'Sociedad', width: 90, cell: (c) => <Mono>{c.company}</Mono>, sortValue: (c) => c.company },
      { id: 'desc', header: 'Descripción', width: 'minmax(260px, 3fr)', cell: (c) => c.desc, sortValue: (c) => c.desc },
    ],
    [],
  )
  return <DataTable aria-label="Centros de coste" rows={core.costCenters} columns={columns} getRowId={(c) => c.id} globalKeys />
}

function BankAccounts({ core }: { core: DatasetCore }) {
  const navigate = useNavigate()
  const month = useApi().meta.month
  const columns = useMemo<Column<BankAccount>[]>(
    () => [
      { id: 'id', header: 'Cuenta', width: 150, cell: (b) => <Mono>{b.id}</Mono>, sortValue: (b) => b.id },
      { id: 'company', header: 'Sociedad', width: 80, cell: (b) => <Mono>{b.company}</Mono>, sortValue: (b) => b.company },
      { id: 'bank', header: 'Banco', width: 'minmax(160px, 1fr)', cell: (b) => b.bank, sortValue: (b) => b.bank },
      { id: 'iban', header: 'IBAN / CLABE', width: 'minmax(220px, 1.5fr)', cell: (b) => mono(b.iban ?? b.clabe) },
      { id: 'gl', header: 'Cuenta contable', width: 130, cell: (b) => <TextLink to={dataPath.account(b.gl_account)} mono>{b.gl_account}</TextLink> },
      { id: 'currency', header: 'Moneda', width: 70, cell: (b) => b.currency },
      { id: 'format', header: 'Extracto', width: 90, cell: (b) => b.statement_format },
      { id: 'roles', header: 'Uso', width: 'minmax(140px, 1fr)', cell: (b) => b.roles.join(', ') },
    ],
    [],
  )
  return (
    <DataTable
      aria-label="Cuentas bancarias"
      rows={core.bankAccounts}
      columns={columns}
      getRowId={(b) => b.id}
      onOpen={(b) => navigate(dataPath.statement(b.id, month))}
      globalKeys
    />
  )
}

