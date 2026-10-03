// `/` Resumen: ¿cómo ha ido el cierre? Opening sentence, vitals, process, pulse, controls and what needs a person.
import { useMemo, useState } from 'react'
import { FolderOpen, PlayCircle } from 'lucide-react'
import { Button, ButtonLink, EmptyState, Page, QueryState, Skeleton, toast } from '@/components'
import type { DatasetApi, DerivedRun, RunBundle } from '@/domain/types'
import { useDatasetStore, useRunStore } from '@/data/stores'
import { useActiveRun, useDerivedRun } from '@/engine'
import { useOverridesStore } from '@/features/attention/overridesStore'
import { pendingAttentionItems } from '@/shell/attentionBadge'
import { CloseControls } from './CloseControls'
import { Hero } from './Hero'
import { ItemMosaic } from './ItemMosaic'
import { attentionSummary, balanceSummary, eurConverter, longMonth } from './model'
import { LastRun, NeedsYou } from './NeedsYou'
import { ProcessDag } from './ProcessDag'
import { TaskCards } from './TaskCards'
import { Vitals } from './Vitals'
import styles from './Overview.module.css'

export default function OverviewPage() {
  const { status, data, error } = useDerivedRun()
  const api = useDatasetStore((s) => s.api)
  const run = useActiveRun()

  if (status === 'loading') return <OverviewSkeleton />
  if (status === 'ready' && data && api && run) return <Overview data={data} api={api} run={run} />
  return (
    <Page>
      <QueryState status={status} error={error} idle={api ? <NoRun api={api} /> : <NoDataset />}>
        {null}
      </QueryState>
    </Page>
  )
}

export function Overview({ data, api, run }: { data: DerivedRun; api: DatasetApi; run: RunBundle }) {
  const { core, meta } = api
  const toEur = useMemo(() => eurConverter(core.companies, core.fxRates, meta.month), [core, meta.month])
  const attention = useMemo(() => attentionSummary(data.attention, data.itemsById, toEur), [data.attention, data.itemsById, toEur])
  const overrides = useOverridesStore((s) => s.byRun[run.id])
  const pending = useMemo(() => pendingAttentionItems(data.attention, overrides ?? []), [data.attention, overrides])
  const needs = useMemo(() => attentionSummary(pending, data.itemsById, toEur), [pending, data.itemsById, toEur])
  const balance = useMemo(() => (data.trialBalance ? balanceSummary(data.trialBalance, toEur) : null), [data.trialBalance, toEur])

  return (
    <Page>
      <Hero meta={meta} run={run} stats={data.stats} />
      <Vitals stats={data.stats} attention={attention} balance={balance} scoreTotal={data.score?.total ?? null} manifest={run.manifest} />
      <ProcessDag data={data} run={run} attention={attention} />
      <div className={styles.split}>
        <NeedsYou data={data} pending={pending} attention={needs} />
        <LastRun run={run} />
      </div>
      <div className={styles.split}>
        <ItemMosaic items={data.items} stats={data.stats} />
        <CloseControls data={data} run={run} core={core} toEur={toEur} />
      </div>
      <TaskCards data={data} balance={balance} />
    </Page>
  )
}

function NoDataset() {
  return (
    <EmptyState
      icon={<FolderOpen />}
      title="Todavía no hay ningún cierre"
      description="Sube la carpeta del mes (erp/, inbox/, bank/, tasks/) para empezar."
      action={
        <ButtonLink to="/ejecuciones/nueva" variant="primary">
          Nuevo cierre
        </ButtonLink>
      }
    />
  )
}

function NoRun({ api }: { api: DatasetApi }) {
  const createGoldenRun = useRunStore((s) => s.createGoldenRun)
  const [opening, setOpening] = useState(false)
  const openGolden = () => {
    setOpening(true)
    createGoldenRun()
      .catch((e: unknown) => toast.error('No se pudo abrir la referencia', { description: e instanceof Error ? e.message : String(e) }))
      .finally(() => setOpening(false))
  }
  return (
    <EmptyState
      icon={<PlayCircle />}
      title={`Hay datos de ${longMonth(api.meta.month)}, pero ningún resultado`}
      description="Importa los resultados del agente (las 6 JSONL o un paquete de ejecución) para ver el resumen."
      action={
        <div className={styles.emptyActions}>
          <ButtonLink to="/ejecuciones/nueva" variant="primary">
            Importar resultados
          </ButtonLink>
          {api.meta.inventory.hasGolden && (
            <Button onClick={openGolden} loading={opening}>
              Abrir la referencia (golden)
            </Button>
          )}
        </div>
      }
    />
  )
}

function OverviewSkeleton() {
  return (
    <Page>
      <div className={styles.hero} role="status" aria-label="Cargando el resumen">
        <Skeleton width={260} height={12} />
        <Skeleton width="min(640px, 100%)" height={34} />
        <Skeleton width={360} height={12} />
      </div>
      <div className={styles.vitals}>
        {Array.from({ length: 5 }, (_, i) => (
          <div key={i} className={styles.skeletonMetric}>
            <Skeleton width={80} height={10} />
            <Skeleton width={96} height={24} />
            <Skeleton width={120} height={10} />
          </div>
        ))}
      </div>
      <Skeleton height={112} radius="var(--radius-lg)" />
      <div className={styles.split}>
        <Skeleton height={240} radius="var(--radius-lg)" />
        <Skeleton height={240} radius="var(--radius-lg)" />
      </div>
    </Page>
  )
}
