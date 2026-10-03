// Entregables: validation of the six files against tasks/ and the format rules, score against
// golden, row preview, and the delivery zip (6 JSONL as delivered + manifest.json + overrides.jsonl).
import { useCallback, useMemo, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import clsx from 'clsx'
import { Download } from 'lucide-react'
import { Button, Card, Metric, Mono, Page, PageHeader, QueryState, Section, toast } from '@/components'
import { useDatasetStore } from '@/data/stores'
import type { DerivedRun, RunBundle, TaskKey } from '@/domain/types'
import { DELIVERABLE_FILES, TASK_KEYS } from '@/domain/types'
import { useActiveRun, useDerivedRun } from '@/engine'
import { formatMonth, formatNumber } from '@/lib/format'
import { PageActions } from '@/shell/PageActions'
import { useOpenItem } from '@/shell/useOpenItem'
import { useOverridesStore } from '../attention/overridesStore'
import { filesPresent, rowsDelivered } from '../runs/taskMeta'
import { deliveryFolder, toJsonl } from './deliveryZip'
import { downloadDelivery } from './downloadDelivery'
import { saveFile } from './download'
import { FileValidationList, type OpenKey } from './FileValidationList'
import { PreviewPanel } from './PreviewPanel'
import { ScoreCard } from './ScoreCard'
import s from './DeliverablesPage.module.css'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const NO_OVERRIDES: never[] = []

function Summary({ data, run, overrides }: { data: DerivedRun; run: RunBundle; overrides: number }) {
  const files = TASK_KEYS.map((t) => data.validation.files[t])
  const withErrors = files.filter((f) => f.errors.length).length
  const warnings = files.reduce((n, f) => n + f.warnings.length, 0)
  const status: ReactNode = data.validation.ok ? (
    <span className={s.ok}>Lista</span>
  ) : (
    <span className={s.danger}>{withErrors === 1 ? '1 fichero con errores' : `${formatNumber(withErrors)} ficheros con errores`}</span>
  )
  return (
    <div className={s.summary}>
      <Metric label="Estado de la entrega" value={status} comparison={warnings ? `${formatNumber(warnings)} avisos` : 'sin avisos'} />
      <Metric label="Ficheros" value={`${filesPresent(run)}/6`} comparison={`${formatNumber(rowsDelivered(run))} filas`} />
      <Metric
        label="Asientos descuadrados"
        value={formatNumber(data.stats.unbalancedEntries)}
        comparison={data.stats.unbalancedEntries ? 'deben cuadrar por sociedad' : 'todos cuadran'}
      />
      <Metric label="Correcciones humanas" value={formatNumber(overrides)} comparison={overrides ? 'van en overrides.jsonl' : 'ninguna'} />
      <Metric label="Nota" value={data.score ? formatNumber(data.score.total, { decimals: 2 }) : '—'} comparison={data.score ? 'de 100, como score.py' : 'sin golden/ no hay nota'} />
    </div>
  )
}

export default function DeliverablesPage() {
  const { data, status, error } = useDerivedRun()
  const run = useActiveRun()
  const api = useDatasetStore((st) => st.api)
  const overrides = useOverridesStore((st) => (run ? st.byRun[run.id] : undefined)) ?? NO_OVERRIDES
  const navigate = useNavigate()
  const openItem = useOpenItem()

  const currencies = useMemo(() => new Map((api?.core.companies ?? []).map((c) => [c.code, c.currency])), [api])
  const currency = useCallback((company: unknown) => currencies.get(String(company)) ?? 'EUR', [currencies])

  const openKey = useCallback<OpenKey>(
    (task, key) => {
      if (task === 'bank_rec') return () => navigate(`/tareas/bancos/${encodeURIComponent(key)}`)
      const id = `${task}:${key}`
      return data?.itemsById.has(id) ? () => openItem(id) : null
    },
    [data, navigate, openItem],
  )

  const ready = status === 'ready' && data !== null && run !== null && data.runId === run.id

  const downloadZip = () => {
    if (!run) return
    try {
      const name = downloadDelivery(run)
      toast.success('Entrega descargada', { description: `${name} · ${filesPresent(run)} de 6 ficheros` })
    } catch (e) {
      toast.error('No se pudo generar el zip', { description: message(e) })
    }
  }
  const downloadFile = (task: TaskKey) => {
    if (run) saveFile(DELIVERABLE_FILES[task], toJsonl(run.deliverables[task]), 'application/x-ndjson')
  }

  const meta = api?.meta
  return (
    <Page>
      <PageActions>
        <Button variant="primary" size="sm" leadingIcon={<Download />} disabled={!ready} onClick={downloadZip}>
          Descargar entrega (.zip)
        </Button>
      </PageActions>
      <PageHeader
        title="Entregables"
        subtitle={run && meta ? `${run.label} · ${meta.name} · ${formatMonth(meta.month)}` : 'Las 6 JSONL validadas, su nota y la descarga.'}
      />
      <QueryState status={status} error={error}>
        {() =>
          ready && (
            <>
              <Summary data={data} run={run} overrides={overrides.length} />

              <Section title="Validación por fichero" description="Filas frente a tasks/, claves, asientos cuadrados, céntimos enteros, cuentas del plan y valores permitidos.">
                <Card padding="none">
                  <FileValidationList key={run.id} validation={data.validation} openKey={openKey} onDownload={downloadFile} />
                </Card>
              </Section>

              {data.score && <ScoreCard score={data.score} trialBalance={data.trialBalance} />}

              <Section title="Vista previa" description="Las filas tal como van en la entrega.">
                <PreviewPanel key={run.id} run={run} currency={currency} openKey={openKey} />
              </Section>

              <p className={clsx(s.note)}>
                El zip lleva la carpeta <Mono>{deliveryFolder(run.id)}/</Mono> con las JSONL tal como llegaron, <Mono>manifest.json</Mono> y, si hay correcciones,{' '}
                <Mono>overrides.jsonl</Mono>. Las correcciones humanas no cambian las JSONL: se entregan aparte.
              </p>
            </>
          )
        }
      </QueryState>
    </Page>
  )
}
