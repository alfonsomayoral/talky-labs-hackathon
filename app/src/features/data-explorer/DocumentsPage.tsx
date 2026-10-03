// `/datos/documentos`: the month's inbox (AP documents, billing items, remittances and notices) and its viewer.
import { useMemo, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router'
import { PanelRight } from 'lucide-react'
import { Button, DataTable, FilterBar, Mono, Page, PageHeader, Section, StatusBadge, Tabs, type Column } from '@/components'
import type { DatasetCore, WorkItem } from '@/domain/types'
import { formatDateTime, formatNumber } from '@/lib/format'
import { useOpenItem } from '@/shell/useOpenItem'
import { DetailHeader, Facts, NotFound, SectionTabs, TextLink, useApi, useRunItems } from './common'
import { FileViewer } from './FileViewer'
import { dataPath, fileName } from './model'
import styles from './DataExplorer.module.css'

type Group = 'ap' | 'billing' | 'file'

interface DocRow {
  id: string
  group: Group
  title: string
  from: string | null
  channel: string | null
  received: string | null
  files: string[]
}

const GROUP_LABEL: Record<Group, string> = { ap: 'Facturas de proveedor', billing: 'Facturación', file: 'Remesas y avisos' }
const GROUP_ORDER: Group[] = ['ap', 'billing', 'file']

function documentRows(core: DatasetCore): DocRow[] {
  const customers = new Map(core.customers.map((c) => [c.id, c.name]))
  return [
    ...core.apInbox.map((d) => ({
      id: d.docId,
      group: 'ap' as const,
      title: d.message.subject ?? d.files.map(fileName).join(', '),
      from: d.message.from ?? d.message.uploaded_by ?? d.message.source ?? null,
      channel: d.message.channel,
      received: d.message.received_at,
      files: d.files,
    })),
    ...core.arInbox.billing.map((b) => ({
      id: b.item,
      group: 'billing' as const,
      title: b.meta ? `${b.meta.type} · ${b.meta.contract}` : b.files.map(fileName).join(', '),
      from: b.meta ? (customers.get(b.meta.customer) ?? b.meta.customer) : null,
      channel: null,
      received: null,
      files: b.files,
    })),
    ...[...core.arInbox.remittances, ...core.arInbox.notices].map((path) => ({
      id: path,
      group: 'file' as const,
      title: fileName(path),
      from: null,
      channel: null,
      received: null,
      files: [path],
    })),
  ]
}

const itemIdOf = (row: Pick<DocRow, 'group' | 'id'>) => (row.group === 'ap' ? `ap:${row.id}` : row.group === 'billing' ? `ar_billing:${row.id}` : null)

export function DocumentsPage() {
  const { core } = useApi()
  const navigate = useNavigate()
  const run = useRunItems()
  const [query, setQuery] = useState('')
  const all = useMemo(() => documentRows(core), [core])
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase()
    return q ? all.filter((r) => [r.id, r.title, r.from ?? ''].some((s) => s.toLowerCase().includes(q))) : all
  }, [all, query])
  const columns = useMemo<Column<DocRow>[]>(
    () => [
      { id: 'id', header: 'Documento', width: 'minmax(170px, 1fr)', cell: (r) => <Mono>{r.group === 'file' ? fileName(r.id) : r.id}</Mono>, sortValue: (r) => r.id },
      { id: 'received', header: 'Recibido', width: 160, cell: (r) => (r.received ? formatDateTime(r.received) : null), sortValue: (r) => r.received },
      { id: 'channel', header: 'Canal', width: 90, cell: (r) => r.channel, sortValue: (r) => r.channel },
      { id: 'from', header: 'Remitente', width: 'minmax(180px, 1.5fr)', cell: (r) => r.from, sortValue: (r) => r.from },
      { id: 'title', header: 'Asunto', width: 'minmax(220px, 2fr)', cell: (r) => r.title },
      { id: 'files', header: 'Ficheros', width: 80, align: 'right', cell: (r) => r.files.length },
      {
        id: 'item',
        header: 'Partida',
        width: 150,
        cell: (r) => {
          const id = itemIdOf(r)
          const item = id ? run?.itemsById.get(id) : undefined
          return item ? <StatusBadge status={item.status} /> : null
        },
      },
    ],
    [run],
  )
  return (
    <Page fill>
      <PageHeader
        title="Datos"
        subtitle="Bandeja de entrada del mes: documentos de proveedor, partidas de facturación, remesas y avisos."
        filters={
          <div className={styles.headerStack}>
            <SectionTabs />
            <FilterBar end={<span className={styles.count}>{`${formatNumber(rows.length)} de ${formatNumber(all.length)}`}</span>}>
              <input className={styles.input} type="search" aria-label="Buscar documentos" placeholder="Id, asunto o remitente…" value={query} onChange={(e) => setQuery(e.target.value)} size={32} />
            </FilterBar>
          </div>
        }
      />
      <DataTable
        aria-label="Documentos"
        rows={rows}
        columns={columns}
        getRowId={(r) => `${r.group}:${r.id}`}
        groupBy={(r) => r.group}
        groupOrder={GROUP_ORDER}
        renderGroup={(k) => GROUP_LABEL[k as Group]}
        onOpen={(r) => navigate(r.group === 'file' ? dataPath.file(r.id) : dataPath.document(r.id))}
        globalKeys
      />
    </Page>
  )
}

/** The item of the run behind a document, and the vendor its evidence names. */
function vendorOf(item: WorkItem | undefined): string | null {
  const ref = item?.evidence.find((e) => e.kind === 'erp' && e.file === 'erp/vendors.jsonl')
  return ref?.kind === 'erp' ? ref.key : null
}

export function DocumentPage() {
  const { id = '' } = useParams()
  const api = useApi()
  const run = useRunItems()
  const openItem = useOpenItem()
  const ap = api.core.apInbox.find((d) => d.docId === id)
  const billing = ap ? undefined : api.core.arInbox.billing.find((b) => b.item === id)
  const files = ap?.files ?? billing?.files ?? []
  const [selected, setSelected] = useState(0)
  if (!ap && !billing) return <NotFound what={`No hay ningún documento ${id} en la bandeja`} />

  const itemId = ap ? `ap:${id}` : `ar_billing:${id}`
  const item = run?.itemsById.get(itemId)
  const vendor = vendorOf(item)
  const customer = billing?.meta?.customer
  const file = files[Math.min(selected, files.length - 1)]

  return (
    <Page>
      <DetailHeader
        crumbs={[{ label: 'Datos', to: '/datos' }, { label: 'Documentos', to: '/datos/documentos' }, { label: id }]}
        title={<Mono>{id}</Mono>}
        subtitle={ap?.message.subject ?? (billing?.meta ? `${billing.meta.type} · ${billing.meta.contract}` : undefined)}
        actions={
          item && (
            <Button variant="primary" leadingIcon={<PanelRight />} onClick={() => openItem(itemId)}>
              Abrir la partida
            </Button>
          )
        }
      />
      <Facts
        items={
          ap
            ? [
                { label: 'Canal', value: ap.message.channel },
                { label: 'Recibido', value: formatDateTime(ap.message.received_at) },
                { label: 'Buzón', value: ap.message.mailbox },
                { label: 'Remitente', value: ap.message.from ?? ap.message.uploaded_by ?? ap.message.source ?? '—' },
                ...(vendor ? [{ label: 'Proveedor', value: <TextLink to={dataPath.vendor(vendor)} mono>{vendor}</TextLink> }] : []),
                ...(item ? [{ label: 'Partida', value: <StatusBadge status={item.status} /> }] : []),
              ]
            : [
                { label: 'Tipo', value: billing!.meta?.type ?? '—' },
                { label: 'Sociedad', value: billing!.meta ? <Mono>{billing!.meta.company}</Mono> : '—' },
                { label: 'Contrato', value: billing!.meta ? <Mono>{billing!.meta.contract}</Mono> : '—' },
                { label: 'Cliente', value: customer ? <TextLink to={dataPath.customer(customer)} mono>{customer}</TextLink> : '—' },
                { label: 'Mes', value: billing!.meta?.month ?? '—' },
                ...(item ? [{ label: 'Partida', value: <StatusBadge status={item.status} /> }] : []),
              ]
        }
      />
      {ap?.message.body && (
        <Section title="Mensaje">
          <p className={styles.body}>{ap.message.body}</p>
        </Section>
      )}
      <Section title="Ficheros" count={files.length}>
        {files.length > 1 && <Tabs aria-label="Ficheros" tabs={files.map((f, i) => ({ id: String(i), label: fileName(f) }))} value={String(selected)} onChange={(v) => setSelected(Number(v))} />}
        {file ? <FileViewer api={api} path={file} /> : <p className={styles.muted}>Sin ficheros adjuntos.</p>}
      </Section>
    </Page>
  )
}

export function LooseFilePage() {
  const [params] = useSearchParams()
  const api = useApi()
  const path = params.get('path') ?? ''
  if (!path.startsWith('inbox/')) return <NotFound what="Ese fichero no está en la bandeja" />
  return (
    <Page>
      <DetailHeader crumbs={[{ label: 'Datos', to: '/datos' }, { label: 'Documentos', to: '/datos/documentos' }, { label: fileName(path) }]} title={fileName(path)} subtitle={<Mono>{path}</Mono>} />
      <FileViewer api={api} path={path} />
    </Page>
  )
}
