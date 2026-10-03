// /dev/ui — every base component with realistic Kalmora samples. Dev reference for feature agents.
import { useMemo, useState, type ReactNode } from 'react'
import { Download, Ellipsis, FileText, Filter, Inbox, PanelRight, Play, Plus, RefreshCw, Trash2 } from 'lucide-react'
import type { ItemStatus, Priority, Provenance, TaskKey } from '@/domain/types'
import { PageActions } from '@/shell/PageActions'
import { useActiveItemId, useOpenItem } from '@/shell/useOpenItem'
import { formatNumber } from '@/lib/format'
import {
  Amount,
  Badge,
  Breadcrumb,
  Button,
  ButtonLink,
  Card,
  ConfidenceBand,
  DataTable,
  Dialog,
  EmptyState,
  FilterBar,
  FilterChip,
  IconButton,
  ITEM_STATUS,
  ITEM_STATUS_ORDER,
  Kbd,
  KeyValue,
  Menu,
  Metric,
  Mono,
  Page,
  PageHeader,
  Pill,
  PriorityBadge,
  ProgressBar,
  ProvenanceBadge,
  QueryState,
  Section,
  SegmentedControl,
  SidePanel,
  Skeleton,
  Sparkline,
  StatusBadge,
  StatusDot,
  Tabs,
  Tooltip,
  ViewOptions,
  statusSegments,
  toast,
  type Column,
  type SortState,
  type Tone,
} from '@/components'
import { makeDemoRows, TASK_LABEL, type DemoRow } from './demoData'
import styles from './Gallery.module.css'

const SWATCHES: { name: string; value: string }[][] = [
  [
    { name: '--brand', value: '#F97316' },
    { name: '--brand-hover', value: '#EA580C' },
    { name: '--brand-ink', value: '#C2410C' },
    { name: '--brand-soft', value: '#FFF7ED' },
    { name: '--brand-border', value: '#FED7AA' },
  ],
  [
    { name: '--ink', value: '#09090B' },
    { name: '--ink-2', value: '#4B5563' },
    { name: '--ink-3', value: '#6B7280' },
    { name: '--ink-4', value: '#9CA3AF' },
    { name: '--line', value: '#E4E4E7' },
    { name: '--bg-muted', value: '#F4F4F5' },
    { name: '--ground', value: '#F4F3EF' },
  ],
  [
    { name: '--ok', value: '#059669' },
    { name: '--warn', value: '#D97706' },
    { name: '--danger', value: '#DC2626' },
    { name: '--info', value: '#2563EB' },
    { name: '--neutral', value: '#9CA3AF' },
  ],
]

const TONES: Tone[] = ['neutral', 'brand', 'ok', 'warn', 'danger', 'info']
const PROVENANCES: Provenance[] = ['RULE', 'HISTORY', 'MODEL', 'HUMAN', 'REFERENCE']
const PRIORITIES: Priority[] = ['P0', 'P1', 'P2', 'P3']
const ROWS = makeDemoRows(2000)

function Demo({ title, children, wide }: { title: string; children: ReactNode; wide?: boolean }) {
  return (
    <div className={wide ? `${styles.demo} ${styles.wide}` : styles.demo}>
      <div className={styles.demoTitle}>{title}</div>
      <div className={styles.demoBody}>{children}</div>
    </div>
  )
}

function counts<K extends string>(rows: DemoRow[], key: (r: DemoRow) => K): Map<K, number> {
  const map = new Map<K, number>()
  for (const r of rows) map.set(key(r), (map.get(key(r)) ?? 0) + 1)
  return map
}

function ListDemo() {
  const openItem = useOpenItem()
  const activeItemId = useActiveItemId()
  const [statuses, setStatuses] = useState<string[]>([])
  const [tasks, setTasks] = useState<string[]>([])
  const [companies, setCompanies] = useState<string[]>([])
  const [groupBy, setGroupBy] = useState<string | null>('status')
  const [sort, setSort] = useState<SortState | null>({ columnId: 'amount', direction: 'desc' })
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const filtered = useMemo(
    () =>
      ROWS.filter(
        (r) =>
          (statuses.length === 0 || statuses.includes(r.status)) &&
          (tasks.length === 0 || tasks.includes(r.task)) &&
          (companies.length === 0 || companies.includes(r.company)),
      ),
    [statuses, tasks, companies],
  )

  const statusCounts = counts(ROWS, (r) => r.status)
  const taskCounts = counts(ROWS, (r) => r.task)
  const companyCounts = counts(ROWS, (r) => r.company)

  const columns = useMemo<Column<DemoRow>[]>(
    () => [
      { id: 'id', header: 'Partida', width: 230, cell: (r) => <Mono>{r.id}</Mono>, sortValue: (r) => r.id },
      { id: 'counterparty', header: 'Contraparte', width: 'minmax(180px, 1fr)', cell: (r) => <span className={styles.ellipsis}>{r.counterparty}</span>, sortValue: (r) => r.counterparty },
      { id: 'task', header: 'Tarea', width: 110, cell: (r) => <span className={styles.muted}>{TASK_LABEL[r.task]}</span>, sortValue: (r) => TASK_LABEL[r.task] },
      { id: 'company', header: 'Sociedad', width: 100, cell: (r) => <Mono muted>{r.company}</Mono>, sortValue: (r) => r.company },
      { id: 'outcome', header: 'Decisión', width: 170, cell: (r) => <Mono muted>{r.outcome}</Mono>, sortValue: (r) => r.outcome },
      { id: 'amount', header: 'Importe', width: 150, align: 'right', cell: (r) => <Amount cents={r.amount} currency={r.currency} />, sortValue: (r) => r.amount },
      {
        id: 'status',
        header: 'Estado',
        width: 150,
        cell: (r) => (
          <>
            <StatusDot status={r.status} label="" />
            <span>{ITEM_STATUS[r.status].label}</span>
          </>
        ),
        sortValue: (r) => ITEM_STATUS_ORDER.indexOf(r.status),
      },
      { id: 'provenance', header: 'Origen', width: 130, cell: (r) => <ProvenanceBadge provenance={r.provenance} />, sortValue: (r) => r.provenance },
      { id: 'confidence', header: 'Confianza', width: 110, cell: (r) => <ConfidenceBand value={r.confidence} />, sortValue: (r) => r.confidence },
    ],
    [],
  )

  const groupFns: Record<string, (r: DemoRow) => string> = {
    status: (r) => r.status,
    task: (r) => TASK_LABEL[r.task],
    company: (r) => r.company,
  }
  const anyFilter = statuses.length + tasks.length + companies.length > 0

  return (
    <div className={styles.listDemo}>
      <FilterBar
        onClear={anyFilter ? () => (setStatuses([]), setTasks([]), setCompanies([])) : undefined}
        end={
          <>
            <span className={styles.muted}>{formatNumber(filtered.length)} partidas</span>
            <ViewOptions
              groupBy={{
                options: [
                  { value: 'status', label: 'Estado' },
                  { value: 'task', label: 'Tarea' },
                  { value: 'company', label: 'Sociedad' },
                ],
                value: groupBy,
                onChange: setGroupBy,
              }}
              sort={{
                options: columns.filter((c) => c.sortValue).map((c) => ({ value: c.id, label: String(c.header) })),
                value: sort,
                onChange: setSort,
              }}
            />
          </>
        }
      >
        <FilterChip
          label="Estado"
          icon={<Filter />}
          selected={statuses}
          onChange={setStatuses}
          options={ITEM_STATUS_ORDER.map((s) => ({ value: s, label: ITEM_STATUS[s].label, count: statusCounts.get(s) ?? 0, icon: <StatusDot status={s} label="" /> }))}
        />
        <FilterChip
          label="Tarea"
          selected={tasks}
          onChange={setTasks}
          options={(Object.keys(TASK_LABEL) as TaskKey[]).map((t) => ({ value: t, label: TASK_LABEL[t], count: taskCounts.get(t) ?? 0 }))}
        />
        <FilterChip
          label="Sociedad"
          selected={companies}
          onChange={setCompanies}
          searchable
          options={[...companyCounts.keys()].sort().map((c) => ({ value: c, label: c, count: companyCounts.get(c) }))}
        />
      </FilterBar>
      <div className={styles.tableFrame}>
        <DataTable
          aria-label="Partidas de ejemplo"
          rows={filtered}
          columns={columns}
          getRowId={(r) => r.id}
          height={460}
          sort={sort}
          onSortChange={setSort}
          groupBy={groupBy ? groupFns[groupBy] : undefined}
          groupOrder={groupBy === 'status' ? ITEM_STATUS_ORDER : undefined}
          renderGroup={
            groupBy === 'status'
              ? (key) => (
                  <>
                    <StatusDot status={key as ItemStatus} label="" />
                    {ITEM_STATUS[key as ItemStatus].label}
                  </>
                )
              : undefined
          }
          selectedId={activeItemId ?? selectedId}
          onSelectedChange={(id) => {
            setSelectedId(id)
            if (id && activeItemId) openItem(id)
          }}
          onOpen={(r) => openItem(r.id)}
          globalKeys
        />
      </div>
      <p className={styles.note}>
        2.000 filas virtualizadas. <Kbd>J</Kbd>
        <Kbd>K</Kbd> o <Kbd>↓</Kbd>
        <Kbd>↑</Kbd> para moverse, <Kbd>↵</Kbd> abre el panel de partida real (<Mono>?item=</Mono>); con el panel abierto, J/K cambian de partida.
      </p>
    </div>
  )
}

function OverlaysDemo() {
  const [panelOpen, setPanelOpen] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)
  const [deleting, setDeleting] = useState(false)

  return (
    <div className={styles.row}>
      <Button leadingIcon={<PanelRight />} onClick={() => setPanelOpen(true)}>
        Abrir panel lateral
      </Button>
      <Button variant="danger" leadingIcon={<Trash2 />} onClick={() => setDialogOpen(true)}>
        Descartar ejecución
      </Button>
      <Menu
        aria-label="Acciones de la partida"
        items={[
          { type: 'label', id: 'l', label: 'Partida API004128' },
          { id: 'accept', label: 'Aceptar recomendación', icon: <FileText />, hint: 'A', onSelect: () => toast.success('Recomendación aceptada') },
          { id: 'alt', label: 'Elegir alternativa', description: 'HOLD · p = 0,06', onSelect: () => toast('Alternativa elegida') },
          { id: 'snooze', label: 'Posponer', disabled: true, onSelect: () => {} },
          { type: 'separator', id: 's' },
          { id: 'discard', label: 'Descartar corrección', danger: true, onSelect: () => toast.error('Corrección descartada') },
        ]}
        trigger={<Button trailingIcon={<Ellipsis />}>Menú</Button>}
      />
      <Tooltip content="Descargar las 6 JSONL y el manifiesto" shortcut={['D']}>
        <Button variant="ghost" leadingIcon={<Download />}>
          Con tooltip
        </Button>
      </Tooltip>
      <Button onClick={() => toast('Ejecución importada', { description: 'dev-2026-07-r003 · 6 ficheros' })}>Toast</Button>
      <Button onClick={() => toast.success('Entrega validada', { description: 'Nota 100,00 · coincide con score.py' })}>Toast ok</Button>
      <Button
        onClick={() =>
          toast.error('Asiento descuadrado', {
            description: 'API004151: Σdebe ≠ Σhaber por 0,01 €',
            action: { label: 'Ver', onClick: () => toast('Abriendo partida…') },
          })
        }
      >
        Toast error
      </Button>

      <SidePanel
        open={panelOpen}
        onClose={() => setPanelOpen(false)}
        title={<Mono>ap:API004128</Mono>}
        actions={<IconButton icon={<Ellipsis />} label="Más acciones" size="sm" tooltipSide="bottom" />}
        footer={
          <>
            <Button onClick={() => setPanelOpen(false)}>Cerrar</Button>
            <Button variant="primary">Aceptar</Button>
          </>
        }
      >
        <div className={styles.panelBody}>
          <div className={styles.row}>
            <StatusBadge status="AUTO" />
            <ProvenanceBadge provenance="RULE" />
            <ConfidenceBand value={0.97} showValue />
          </div>
          <h2 className={styles.panelTitle}>Certificación nº 7 — Ferralla Norte, S.L.</h2>
          <KeyValue
            items={[
              { label: 'Documento', value: 'API004128', mono: true },
              { label: 'Sociedad', value: '1100 · Kalmora Construcción, S.A.U.' },
              { label: 'Proveedor', value: 'V100045', mono: true },
              { label: 'Importe', value: <Amount cents={4202872} /> },
              { label: 'Retención garantía', value: <Amount cents={-210144} signed colorize /> },
              { label: 'Cuenta', value: '40090000', mono: true },
              { label: 'Regla', value: '§2.2 Inversión del sujeto pasivo' },
            ]}
          />
        </div>
      </SidePanel>

      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title="¿Descartar la ejecución?"
        description="Se quitará dev-2026-07-r003 de este navegador. Los ficheros originales no se tocan."
        size="sm"
        footer={
          <>
            <Button onClick={() => setDialogOpen(false)}>Cancelar</Button>
            <Button
              variant="danger"
              loading={deleting}
              onClick={() => {
                setDeleting(true)
                setTimeout(() => {
                  setDeleting(false)
                  setDialogOpen(false)
                  toast.success('Ejecución descartada')
                }, 900)
              }}
            >
              Descartar
            </Button>
          </>
        }
      />
    </div>
  )
}

export default function GalleryPage() {
  const [tab, setTab] = useState('summary')
  const [view, setView] = useState<'list' | 'grid'>('list')
  const [queryStatus, setQueryStatus] = useState<'idle' | 'loading' | 'ready' | 'error'>('loading')

  return (
    <Page>
      <PageActions>
        <Button size="sm" leadingIcon={<RefreshCw />} onClick={() => toast('Acción inyectada desde la página')}>
          Acción de página
        </Button>
      </PageActions>

      <PageHeader
        breadcrumb={<Breadcrumb items={[{ label: 'Desarrollo' }, { label: 'Galería', to: '/dev/ui' }, { label: 'Componentes' }]} />}
        title="Galería de componentes"
        subtitle="Primitivas de la interfaz con muestras de Kalmora. Convenciones en src/components/README.md."
        actions={
          <>
            <Button leadingIcon={<Download />}>Exportar</Button>
            <Button variant="primary" leadingIcon={<Play />}>
              Cerrar el mes
            </Button>
          </>
        }
      />

      <Section title="Tokens" description="Marca Talky: el naranja solo para acciones primarias, selección y foco; el color de estado solo para estados.">
        <div className={styles.swatchRows}>
          {SWATCHES.map((row, i) => (
            <div key={i} className={styles.swatches}>
              {row.map((s) => (
                <div key={s.name} className={styles.swatch}>
                  <span className={styles.swatchColor} style={{ background: `var(${s.name})` }} />
                  <Mono>{s.name}</Mono>
                  <Mono muted>{s.value}</Mono>
                </div>
              ))}
            </div>
          ))}
        </div>
        <div className={styles.typeScale}>
          <span style={{ fontSize: 32, fontWeight: 600, letterSpacing: '-0.025em' }}>32 · Cifra clave</span>
          <span style={{ fontSize: 24, fontWeight: 600 }}>24 · Indicador</span>
          <span style={{ fontSize: 20, fontWeight: 600 }}>20 · Título de página</span>
          <span style={{ fontSize: 14, fontWeight: 600 }}>14 · Título de sección</span>
          <span>13 · Texto base de la interfaz</span>
          <span style={{ fontSize: 12, color: 'var(--ink-3)' }}>12 · Etiquetas y tablas secundarias</span>
          <span className={styles.serif}>El agente cerró julio con 1,2 M€ pendientes de revisar.</span>
          <Mono>API004128 · 40090000 · BL0000085 · §2.2.3</Mono>
        </div>
      </Section>

      <Section title="Acción">
        <div className={styles.grid}>
          <Demo title="Button · variantes">
            <Button variant="primary" leadingIcon={<Plus />}>
              Nuevo cierre
            </Button>
            <Button>Importar</Button>
            <Button variant="ghost">Cancelar</Button>
            <Button variant="danger">Descartar</Button>
          </Demo>
          <Demo title="Button · tamaños y estados">
            <Button variant="primary" size="sm">
              Aceptar
            </Button>
            <Button size="sm" leadingIcon={<Download />}>
              Zip
            </Button>
            <Button variant="primary" loading>
              Validando
            </Button>
            <Button disabled>Deshabilitado</Button>
            <ButtonLink to="/ejecuciones" variant="ghost" size="sm">
              Enlace con estilo
            </ButtonLink>
          </Demo>
          <Demo title="IconButton · Kbd">
            <IconButton icon={<RefreshCw />} label="Recalcular" shortcut={['R']} />
            <IconButton icon={<Download />} label="Descargar" variant="secondary" />
            <IconButton icon={<PanelRight />} label="Panel lateral" active />
            <IconButton icon={<Ellipsis />} label="Más" size="sm" />
            <span className={styles.row}>
              <Kbd>⌘</Kbd>
              <Kbd>K</Kbd>
              <Kbd>G</Kbd>
              <Kbd>R</Kbd>
              <Kbd>Esc</Kbd>
            </span>
          </Demo>
        </div>
      </Section>

      <Section title="Estado">
        <div className={styles.grid}>
          <Demo title="StatusDot · StatusBadge">
            {ITEM_STATUS_ORDER.map((s) => (
              <StatusBadge key={s} status={s} />
            ))}
            <span className={styles.row}>
              <StatusDot tone="brand" pulse label="En curso" /> <span className={styles.muted}>En curso</span>
            </span>
          </Demo>
          <Demo title="PriorityBadge">
            {PRIORITIES.map((p) => (
              <PriorityBadge key={p} priority={p} />
            ))}
          </Demo>
          <Demo title="Badge · tonos (soft / outline + dot)">
            {TONES.map((t) => (
              <Badge key={t} tone={t}>
                {t}
              </Badge>
            ))}
            {TONES.slice(2, 5).map((t) => (
              <Badge key={`o-${t}`} tone={t} variant="outline" dot>
                {t}
              </Badge>
            ))}
          </Demo>
          <Demo title="Pill">
            <Pill>1100</Pill>
            <Pill>EUR</Pill>
            <Pill tone="brand" count={12}>
              Atención
            </Pill>
            <Pill icon={<Inbox />} count={305}>
              Documentos
            </Pill>
            <Pill onRemove={() => toast('Filtro quitado')}>Sociedad: 3100</Pill>
          </Demo>
          <Demo title="ProvenanceBadge">
            {PROVENANCES.map((p) => (
              <ProvenanceBadge key={p} provenance={p} />
            ))}
            {PROVENANCES.map((p) => (
              <ProvenanceBadge key={`c-${p}`} provenance={p} compact />
            ))}
          </Demo>
          <Demo title="ConfidenceBand (0,9 / 0,7)">
            <ConfidenceBand value={0.97} showValue />
            <ConfidenceBand value={0.82} showValue />
            <ConfidenceBand value={0.41} showValue />
            <span className={styles.muted}>null →</span>
            <ConfidenceBand value={null} />
          </Demo>
        </div>
      </Section>

      <Section title="Datos">
        <div className={styles.grid}>
          <Demo title="Amount">
            <div className={styles.amounts}>
              <span>EUR</span>
              <Amount cents={4202872} />
              <span>Con signo</span>
              <Amount cents={-1550000} signed colorize />
              <span>Compacto</span>
              <Amount cents={123456789} compact />
              <span>MXN (3100)</span>
              <Amount cents={250000000} currency="MXN" />
              <span>Mono</span>
              <Amount cents={4202872} mono />
              <span>Cero / nulo</span>
              <span className={styles.row}>
                <Amount cents={0} /> <Amount cents={null} />
              </span>
            </div>
          </Demo>
          <Demo title="KeyValue">
            <KeyValue
              items={[
                { label: 'Documento', value: 'API004128', mono: true },
                { label: 'Proveedor', value: 'Ferralla Norte, S.L.' },
                { label: 'IBAN ficha', value: 'ES93 0049 1500 0512 3456 7892', mono: true },
                { label: 'Importe', value: <Amount cents={4202872} /> },
              ]}
            />
          </Demo>
          <Demo title="Sparkline · ProgressBar">
            <span className={styles.row}>
              <Sparkline values={[8.1, 7.9, 8.4, 8.2, 9.1, 8.8, 9.6]} aria-label="Gasto mensual del proveedor" />
              <Sparkline values={[3, 4, 3.5, 5, 6.2, 7, 8.4]} tone="ok" area />
              <Sparkline values={[9, 8, 8.5, 6, 5.2, 4, 2.1]} tone="danger" />
            </span>
            <ProgressBar value={0.68} label="Progreso de AP" />
            <ProgressBar value={9} max={12} size="sm" tone="ok" label="Bancos conciliados" />
          </Demo>
          <Demo title="ProgressBar · apilada por estado" wide>
            <ProgressBar segments={statusSegments({ AUTO: 1561, NEEDS_HUMAN: 241, BLOCKED: 119, OPEN: 79 })} showLegend label="Partidas por estado" />
          </Demo>
        </div>
        <div className={styles.metrics}>
          <Metric label="Autonomía" value="87,4 %" delta="+3,1 pp" deltaTone="ok" comparison="vs. ejecución anterior" hint="Partidas resueltas sin intervención humana sobre el total." />
          <Metric label="Te necesitan" value="23" delta={<Amount cents={123456789} compact />} deltaTone="neutral" comparison="en juego" />
          <Metric label="Coste" value="3,51 US$" delta="+0,42" deltaTone="danger" comparison="vs. r002" />
          <Metric label="Hueco del balance" value="—" loading />
        </div>
      </Section>

      <Section title="Estructura">
        <div className={styles.grid}>
          <Card title="Card con acciones" description="Superficie blanca, borde fino" actions={<IconButton icon={<Ellipsis />} label="Más" size="sm" />}>
            <ProgressBar segments={statusSegments({ AUTO: 284, NEEDS_HUMAN: 12, BLOCKED: 9 })} showLegend />
          </Card>
          <Card interactive title="Card interactiva" description="Bandeja AP · 30 %">
            <span className={styles.bigNumber}>305</span> <span className={styles.muted}>documentos</span>
          </Card>
          <Card padding="none" title="Card sin relleno">
            <EmptyState size="sm" icon={<Inbox />} title="Nada pendiente" description="Todas las partidas están resueltas." />
          </Card>
        </div>
        <Demo title="Tabs · SegmentedControl" wide>
          <Tabs
            aria-label="Pestañas de partida"
            value={tab}
            onChange={setTab}
            tabs={[
              { id: 'summary', label: 'Resumen' },
              { id: 'entry', label: 'Asiento', count: 7 },
              { id: 'evidence', label: 'Evidencia', count: 3 },
              { id: 'trace', label: 'Traza' },
              { id: 'golden', label: 'Golden', disabled: true },
            ]}
          />
          <SegmentedControl
            aria-label="Vista"
            value={view}
            onChange={setView}
            options={[
              { value: 'list', label: 'Lista' },
              { value: 'grid', label: 'Mosaico' },
            ]}
          />
        </Demo>
        <div className={styles.grid}>
          <Demo title="QueryState">
            <SegmentedControl
              aria-label="Estado de carga"
              size="sm"
              value={queryStatus}
              onChange={setQueryStatus}
              options={[
                { value: 'idle', label: 'idle' },
                { value: 'loading', label: 'loading' },
                { value: 'error', label: 'error' },
                { value: 'ready', label: 'ready' },
              ]}
            />
            <div className={styles.queryBox}>
              <QueryState status={queryStatus} error="No se encontró deliverables/ap.jsonl" onRetry={() => setQueryStatus('loading')}>
                {() => <EmptyState size="sm" title="Datos listos" description="Aquí va la vista." />}
              </QueryState>
            </div>
          </Demo>
          <Demo title="Skeleton">
            <div className={styles.skeletons}>
              <Skeleton width={140} height={16} />
              <Skeleton lines={3} />
              <Skeleton width={96} height={28} radius="var(--radius-pill)" />
            </div>
          </Demo>
        </div>
      </Section>

      <Section title="Lista" description="FilterBar + FilterChip + ViewOptions + DataTable virtualizada, agrupada por estado.">
        <ListDemo />
      </Section>

      <Section title="Capas" description="SidePanel, Dialog, Menu, Tooltip y Toaster. La página también inyecta un botón en la barra superior con PageActions.">
        <OverlaysDemo />
      </Section>
    </Page>
  )
}
