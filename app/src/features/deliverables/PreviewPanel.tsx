// Rows of each deliverable as delivered: a table per file and the JSON of the selected row.
import { useMemo, useState, type ReactNode } from 'react'
import { ExternalLink } from 'lucide-react'
import { Amount, Button, DataTable, EmptyState, Mono, Tabs, TabPanel, type Column } from '@/components'
import type { RunBundle, TaskKey } from '@/domain/types'
import { DELIVERABLE_FILES } from '@/domain/types'
import { rowKey } from '@/engine'
import { formatNumber } from '@/lib/format'
import { PIPELINE } from '@/domain/catalog/labels'
import type { OpenKey } from './FileValidationList'
import s from './PreviewPanel.module.css'

type Rec = Record<string, unknown>
interface Row {
  id: string
  index: number
  key: string
  row: Rec
}

const str = (v: unknown) => (v === null || v === undefined ? null : String(v))
const num = (v: unknown) => (typeof v === 'number' ? v : null)
const list = (v: unknown): Rec[] => (Array.isArray(v) ? (v as Rec[]) : [])
const code = (v: unknown) => (v == null || v === '' ? <span className={s.muted}>—</span> : <Mono>{String(v)}</Mono>)

/** Lines of every entry in a row, whatever field carries them. */
function entryLines(task: TaskKey, r: Rec): number {
  if (task === 'bank_rec') return list(r.adjustments).reduce((n, a) => n + list(a.lines).length, 0)
  if (task === 'ar_cash' || task === 'ic') return list(r.adjustment).length
  const je = r.journal_entry as Rec | null | undefined
  return je ? list(je.lines).length : 0
}

function taskColumns(task: TaskKey, currency: (company: unknown) => string): Column<Row>[] {
  const amount = (get: (r: Rec) => unknown, header = 'Importe', company: (r: Rec) => unknown = (r) => r.company): Column<Row> => ({
    id: `amount-${header}`,
    header,
    width: 132,
    align: 'right',
    sortValue: (x) => num(get(x.row)),
    cell: (x) => <Amount cents={num(get(x.row))} currency={currency(company(x.row))} />,
  })
  const text = (id: string, header: string, get: (r: Rec) => unknown, width: number | string = 140): Column<Row> => ({
    id,
    header,
    width,
    sortValue: (x) => str(get(x.row)),
    cell: (x) => code(get(x.row)),
  })
  const count = (id: string, header: string, get: (r: Rec) => number): Column<Row> => ({
    id,
    header,
    width: 96,
    align: 'right',
    sortValue: (x) => get(x.row),
    cell: (x) => formatNumber(get(x.row)),
  })
  switch (task) {
    case 'ap':
      return [
        text('decision', 'Decisión', (r) => r.decision),
        text('type', 'Tipo', (r) => r.document_type, 180),
        text('reasons', 'Motivos', (r) => list(r.reasons).join(', ') || null, 'minmax(140px, 1fr)'),
        amount((r) => r.gross, 'Bruto'),
      ]
    case 'ar_billing':
      return [
        text('expected', 'Resultado', (r) => r.expected, 180),
        amount((r) => (r.invoice as Rec | null)?.net, 'Base', (r) => (r.journal_entry as Rec | null)?.company),
        amount((r) => (r.invoice as Rec | null)?.payable, 'A cobrar', (r) => (r.journal_entry as Rec | null)?.company),
      ]
    case 'ar_cash':
      return [
        text('customer', 'Cliente', (r) => r.customer),
        count('apps', 'Aplicaciones', (r) => list(r.applications).length),
        text('residuals', 'Diferencias', (r) => list(r.residuals).map((x) => x.type).join(', ') || null, 'minmax(160px, 1fr)'),
      ]
    case 'bank_rec':
      return [
        text('company', 'Sociedad', (r) => r.company, 96),
        count('matches', 'Casaciones', (r) => list(r.matches).length),
        count('ubank', 'Sin casar banco', (r) => list(r.unmatched_bank).length),
        count('ubook', 'Sin casar libro', (r) => list(r.unmatched_book).length),
        count('adj', 'Ajustes', (r) => list(r.adjustments).length),
      ]
    case 'ic':
      return [
        text('cause', 'Causa', (r) => r.cause, 200),
        text('responsible', 'Responsable', (r) => r.responsible, 110),
        amount((r) => r.amount, 'Importe', () => null),
      ]
    case 'close':
      return [text('type', 'Tipo', (r) => r.type, 150), text('company', 'Sociedad', (r) => r.company, 96), amount((r) => r.amount)]
  }
}

function JsonView({ row, action }: { row: Row | null; action: ReactNode }) {
  if (!row) return <EmptyState size="sm" title="Elige una fila" description="Su JSON aparece aquí tal como va en la entrega." />
  return (
    <div className={s.json}>
      <div className={s.jsonHead}>
        <Mono>{row.key}</Mono>
        <span className={s.muted}>fila {formatNumber(row.index + 1)}</span>
        <span className={s.grow} />
        {action}
      </div>
      <pre className={s.pre}>{JSON.stringify(row.row, null, 2)}</pre>
    </div>
  )
}

function FilePreview({ task, run, currency, openKey }: { task: TaskKey; run: RunBundle; currency: (company: unknown) => string; openKey: OpenKey }) {
  const rows = useMemo<Row[]>(
    () => (run.deliverables[task] as unknown as Rec[]).map((row, index) => ({ id: String(index), index, key: rowKey(task, row), row })),
    [run, task],
  )
  const [selectedId, setSelectedId] = useState<string | null>(rows.length ? '0' : null)
  const columns = useMemo<Column<Row>[]>(
    () => [
      { id: 'n', header: '#', width: 56, align: 'right', sortValue: (x) => x.index, cell: (x) => <span className={s.muted}>{x.index + 1}</span> },
      { id: 'key', header: 'Clave', width: 'minmax(180px, 1.2fr)', sortValue: (x) => x.key, cell: (x) => <Mono>{x.key}</Mono> },
      ...taskColumns(task, currency),
      { id: 'lines', header: 'Líneas de asiento', width: 128, align: 'right', sortValue: (x) => entryLines(task, x.row), cell: (x) => formatNumber(entryLines(task, x.row)) },
    ],
    [task, currency],
  )
  if (!run.present[task]) return <EmptyState size="sm" title={`Sin ${DELIVERABLE_FILES[task]}`} description="La ejecución no trae este fichero." />
  const selected = selectedId != null ? (rows[Number(selectedId)] ?? null) : null
  const open = selected ? openKey(task, selected.key) : null
  return (
    <div className={s.layout}>
      <DataTable
        aria-label={`Filas de ${DELIVERABLE_FILES[task]}`}
        rows={rows}
        columns={columns}
        getRowId={(x) => x.id}
        selectedId={selectedId}
        onSelectedChange={setSelectedId}
        onOpen={(x) => setSelectedId(x.id)}
        height={420}
      />
      <JsonView
        row={selected}
        action={
          open && (
            <Button size="sm" variant="ghost" leadingIcon={<ExternalLink />} onClick={open}>
              Abrir partida
            </Button>
          )
        }
      />
    </div>
  )
}

export function PreviewPanel({ run, currency, openKey }: { run: RunBundle; currency: (company: unknown) => string; openKey: OpenKey }) {
  const [task, setTask] = useState<TaskKey>('ap')
  return (
    <div className={s.wrap}>
      <Tabs
        idPrefix="preview"
        aria-label="Fichero"
        value={task}
        onChange={(id) => setTask(id as TaskKey)}
        tabs={PIPELINE.map((t) => ({ id: t, label: <Mono>{DELIVERABLE_FILES[t]}</Mono>, count: run.present[t] ? run.deliverables[t].length : undefined }))}
      />
      <TabPanel idPrefix="preview" id={task}>
        <FilePreview key={task} task={task} run={run} currency={currency} openKey={openKey} />
      </TabPanel>
    </div>
  )
}
