// Nuevo cierre: 1) load a phase folder (drop, folder, zip, dev-served or previously loaded),
// 2) get the agent's results (backend, import, or the golden reference).
import { useEffect, useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import clsx from 'clsx'
import { BookCheck, Check, CircleCheck, CircleX, FileArchive, FolderOpen, Play, Server, Trash2, Upload, X } from 'lucide-react'
import { Badge, Button, ButtonLink, Card, IconButton, Mono, Page, PageHeader, ProgressBar, toast } from '@/components'
import { useDatasetStore, useRunStore } from '@/data/stores'
import { DELIVERABLE_FILES, TASK_KEYS, type DatasetMeta, type RunBundle } from '@/domain/types'
import { useActiveRun } from '@/engine'
import { formatDateTime, formatMonth, formatNumber } from '@/lib/format'
import { DatasetInventory } from './DatasetInventory'
import { DropZone, FilesPicker, FolderPicker, isSingleZip, ZipPicker } from './FilePickers'
import { ConfirmRemove, type RemoveTarget } from './ConfirmRemove'
import { filesPresent, RUN_SOURCE, runPath } from './taskMeta'
import s from './NewRunPage.module.css'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

/** Loading a phase reads ~800 files and a 40 MB journal: say what it is doing and that it is alive. */
function LoadingCard({ progress: p }: { progress: { phase: string; done: number; total: number } | null }) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const started = Date.now()
    const timer = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [])
  // Phases reported as 0/1 (opening, listing, the journal) have no measurable size.
  const counted = p != null && p.total > 1
  return (
    <Card>
      <div className={s.progress} role="status">
        <div className={s.progressText}>
          <span>{p?.phase ?? 'Cargando'}…</span>
          <span className="tabular">
            {counted && `${formatNumber(p.done)} / ${formatNumber(p.total)} · `}
            {seconds} s
          </span>
        </div>
        <ProgressBar value={counted ? p.done : 0} max={counted ? p.total : 1} indeterminate={!counted} label="Progreso de la carga" />
        <p className={s.progressHint}>Se leen los ficheros de la fase en el navegador; con el diario completo puede tardar unos segundos.</p>
      </div>
    </Card>
  )
}
const SOURCE_KIND: Record<DatasetMeta['sourceKind'], string> = { folder: 'Carpeta', zip: 'Zip', http: 'Servido' }

function Step({ n, title, description, done, disabled, children }: { n: number; title: string; description: string; done?: boolean; disabled?: boolean; children: ReactNode }) {
  return (
    <section className={clsx(s.step, disabled && s.stepDisabled)} aria-disabled={disabled || undefined}>
      <header className={s.stepHeader}>
        <span className={clsx(s.stepNumber, done && s.stepDone)} aria-hidden>
          {done ? <Check /> : n}
        </span>
        <div>
          <h2 className={s.stepTitle}>{title}</h2>
          <p className={s.stepDescription}>{description}</p>
        </div>
      </header>
      <div className={s.stepBody}>{children}</div>
    </section>
  )
}

/** Each visit starts blank: the dataset already open is offered in the list, not preselected. */
function DatasetStep({ chosenId, onChosen }: { chosenId: string | null; onChosen: (id: string) => void }) {
  const ds = useDatasetStore()
  const active = ds.api?.meta ?? null
  const meta = active?.id === chosenId ? active : null
  const [changing, setChanging] = useState(false)
  const [forget, setForget] = useState<RemoveTarget | null>(null)
  const [error, setError] = useState<string | null>(null)
  const busy = ds.status === 'loading'

  useEffect(() => {
    void useDatasetStore.getState().refreshAvailable()
  }, [])

  const load = (fn: () => Promise<DatasetMeta | void>) => {
    setError(null)
    fn().then(
      (m) => {
        setChanging(false)
        if (!m) return
        onChosen(m.id)
        if (m.id !== active?.id) toast.success(`${m.name} cargado`, { description: `Cierre de ${formatMonth(m.month)}` })
      },
      (e: unknown) => setError(message(e)),
    )
  }
  const openFiles = (files: File[]) => (isSingleZip(files) ? ds.loadFromZip(files[0]) : ds.loadFromFolder(files))
  const loadFiles = (files: File[]) => load(() => openFiles(files))

  if (busy) return <LoadingCard progress={ds.progress} />

  const others = ds.datasets.filter((d) => d.id !== meta?.id)
  const reopen = (id: string) => load(() => ds.activate(id).then(() => useDatasetStore.getState().api?.meta))
  const showLoader = !meta || changing

  return (
    <>
      {meta && (
        <div className={s.loaded}>
          <div className={s.loadedHead}>
            <div className={s.loadedTitle}>
              <strong>{meta.name}</strong>
              <Badge variant="outline">{formatMonth(meta.month)}</Badge>
              <span className={s.muted}>
                {SOURCE_KIND[meta.sourceKind]} · cargado {formatDateTime(meta.loadedAt)}
              </span>
            </div>
            <Button size="sm" variant="ghost" leadingIcon={changing ? <X /> : <FolderOpen />} onClick={() => setChanging((c) => !c)}>
              {changing ? 'Cancelar' : 'Cambiar datos'}
            </Button>
          </div>
          <DatasetInventory inventory={meta.inventory} />
        </div>
      )}

      {showLoader && (
        <>
          <DropZone onFiles={(p) => load(async () => openFiles(await p))}>
            <Upload className={s.dropIcon} aria-hidden />
            <div>
              <div className={s.dropTitle}>Arrastra aquí la carpeta de una fase o su .zip</div>
              <div className={s.muted}>
                Con <Mono>erp/</Mono>, <Mono>inbox/</Mono>, <Mono>bank/</Mono>, <Mono>tasks/</Mono> y, si existe, <Mono>golden/</Mono>
              </div>
            </div>
            <div className={s.actions}>
              <FolderPicker variant={meta ? 'secondary' : 'primary'} icon={<FolderOpen />} onFiles={loadFiles}>
                Elegir carpeta
              </FolderPicker>
              <ZipPicker icon={<FileArchive />} onFiles={loadFiles}>
                Elegir .zip
              </ZipPicker>
              {ds.canUploadToBackend() && (
                <ZipPicker icon={<Server />} onFiles={(files) => load(() => ds.uploadToBackend(files[0]))}>
                  Subir .zip al backend
                </ZipPicker>
              )}
            </div>
          </DropZone>

          {ds.available.length > 0 && (
            <Card title="Servidos por el backend o en desarrollo" padding="none">
              <ul className={s.list}>
                {ds.available.map((a) => (
                  <li key={`${a.source}:${a.id}`} className={s.listRow}>
                    <span className={s.listName}>{a.name}</span>
                    <Mono muted>
                      {a.source}:{a.id}
                    </Mono>
                    <span className={s.grow} />
                    {meta?.remoteId === a.id ? (
                      <Badge tone="ok">Cargado</Badge>
                    ) : active?.remoteId === a.id ? (
                      <Button size="sm" onClick={() => onChosen(active.id)}>
                        Usar
                      </Button>
                    ) : (
                      <Button size="sm" onClick={() => load(() => ds.loadFromHttp(a.id))}>
                        Cargar
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {others.length > 0 && (
            <Card title="Cargados antes" padding="none">
              <ul className={s.list}>
                {others.map((d) => (
                  <li key={d.id} className={s.listRow}>
                    <span className={s.listName}>{d.name}</span>
                    <span className={s.muted}>
                      {formatMonth(d.month)} · {SOURCE_KIND[d.sourceKind]} · {formatDateTime(d.loadedAt)}
                    </span>
                    <span className={s.grow} />
                    <Button size="sm" onClick={() => reopen(d.id)}>
                      {d.id === active?.id ? 'Usar' : 'Activar'}
                    </Button>
                    {d.id !== active?.id && (
                      <IconButton
                        size="sm"
                        icon={<Trash2 />}
                        label={`Olvidar ${d.name}`}
                        onClick={() =>
                          setForget({
                            title: 'Olvidar dataset',
                            description: `Se quita «${d.name}» y sus ejecuciones de este navegador. Los ficheros originales no se tocan.`,
                            run: () => ds.remove(d.id),
                          })
                        }
                      />
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      )}

      <ConfirmRemove target={forget} onClose={() => setForget(null)} />

      {(error ?? (ds.status === 'error' ? ds.error : null)) && (
        <p className={s.error} role="alert">
          <CircleX aria-hidden /> {error ?? ds.error}
        </p>
      )}
    </>
  )
}

function ImportedFiles({ run }: { run: RunBundle }) {
  const extras = [
    { name: 'manifest.json', ok: run.manifest !== null },
    { name: 'trace/events.jsonl', ok: run.events !== null },
    { name: 'trace/attention.jsonl', ok: run.attention !== null },
  ]
  return (
    <div className={s.found}>
      <div className={s.foundTitle}>
        {run.label}: {filesPresent(run)} de 6 entregas
      </div>
      <ul className={s.fileList}>
        {TASK_KEYS.map((t) => (
          <li key={t} data-ok={run.present[t]}>
            {run.present[t] ? <CircleCheck aria-label="Encontrado" /> : <CircleX aria-label="No encontrado" />}
            <Mono>{DELIVERABLE_FILES[t]}</Mono>
            {run.present[t] && <span className={s.muted}>{formatNumber(run.deliverables[t].length)} filas</span>}
          </li>
        ))}
        {extras.map((x) => (
          <li key={x.name} data-ok={x.ok} data-optional>
            {x.ok ? <CircleCheck aria-label="Encontrado" /> : <span className={s.dash}>—</span>}
            <Mono muted={!x.ok}>{x.name}</Mono>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ResultsStep({ meta, hasRun, onCreated }: { meta: DatasetMeta; hasRun: boolean; onCreated: (runId: string) => void }) {
  const navigate = useNavigate()
  const runs = useRunStore()
  const apiConfigured = runs.canStartApiRun()
  // The backend can only close a month it has registered: one loaded from it, not a local folder or .zip.
  const onBackend = Boolean(meta.remoteId)
  const [pending, setPending] = useState<'api' | 'import' | 'golden' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [imported, setImported] = useState<RunBundle | null>(null)
  const hasGolden = meta.inventory.hasGolden
  const primary = hasRun ? null : apiConfigured && onBackend ? 'api' : hasGolden ? 'golden' : 'import'

  const attempt = <T,>(kind: 'api' | 'import' | 'golden', fn: () => Promise<T>, done: (r: T) => void) => {
    setError(null)
    setPending(kind)
    fn()
      .then(done, (e: unknown) => setError(message(e)))
      .finally(() => setPending(null))
  }
  const importFiles = (files: File[]) =>
    attempt('import', () => runs.importRun(isSingleZip(files) ? files[0] : files), (run) => {
      setImported(run)
      onCreated(run.id)
      toast.success('Resultados importados', { description: `${run.label} · ${filesPresent(run)} de 6 entregas` })
    })

  return (
    <>
      <div className={s.options}>
        <Card title={<span className={s.optionTitle}><Server aria-hidden /> Cerrar el mes con el backend</span>} description="El agente cierra el mes y la app sigue su progreso en vivo.">
          <div className={s.optionBody}>
            {!apiConfigured && <p className={s.muted}>Define VITE_API_URL para conectar el backend.</p>}
            {apiConfigured && !onBackend && <p className={s.muted}>Estos datos están solo en el navegador. Usa «Subir .zip al backend» en el paso 1 para cerrar el mes aquí.</p>}
            <Button
              variant={primary === 'api' ? 'primary' : 'secondary'}
              size="sm"
              leadingIcon={<Play />}
              disabled={!apiConfigured || !onBackend}
              loading={pending === 'api'}
              onClick={() => attempt('api', () => runs.startApiRun(meta.id), (runId) => navigate(runPath(runId)))}
            >
              Cerrar el mes
            </Button>
          </div>
        </Card>

        <Card title={<span className={s.optionTitle}><Upload aria-hidden /> Importar resultados</span>} description="Las 6 JSONL, la carpeta de un paquete o su .zip.">
          <DropZone className={s.importDrop} disabled={pending === 'import'} onFiles={(p) => void p.then(importFiles, (e: unknown) => setError(message(e)))}>
            <div className={s.actions}>
              <FilesPicker variant={primary === 'import' ? 'primary' : 'secondary'} accept=".jsonl,.json,.zip" onFiles={importFiles} disabled={pending === 'import'}>
                Elegir ficheros
              </FilesPicker>
              <FolderPicker onFiles={importFiles} disabled={pending === 'import'}>
                Carpeta
              </FolderPicker>
              <ZipPicker onFiles={importFiles} disabled={pending === 'import'}>
                .zip
              </ZipPicker>
            </div>
            <span className={s.muted}>{pending === 'import' ? 'Importando…' : 'o arrástralos aquí'}</span>
          </DropZone>
        </Card>

        {hasGolden && (
          <Card title={<span className={s.optionTitle}><BookCheck aria-hidden /> Abrir la solución de referencia</span>} description="Los ficheros de golden/ como ejecución. Su nota es 100.">
            <div className={s.optionBody}>
              <Button
                variant={primary === 'golden' ? 'primary' : 'secondary'}
                size="sm"
                loading={pending === 'golden'}
                onClick={() =>
                  attempt('golden', () => runs.createGoldenRun(), (run) => {
                    onCreated(run.id)
                    toast.success('Referencia abierta', { description: run.label })
                  })
                }
              >
                Abrir referencia
              </Button>
            </div>
          </Card>
        )}
      </div>
      {imported && <ImportedFiles run={imported} />}
      {error && (
        <p className={s.error} role="alert">
          <CircleX aria-hidden /> {error}
        </p>
      )}
    </>
  )
}

export default function NewRunPage() {
  const [chosenId, setChosenId] = useState<string | null>(null)
  const [createdId, setCreatedId] = useState<string | null>(null)
  const active = useDatasetStore((st) => st.api?.meta ?? null)
  const meta = active?.id === chosenId ? active : null
  const run = useActiveRun()
  const activeRun = run && meta && run.id === createdId && run.datasetId === meta.id ? run : null

  return (
    <Page width="narrow">
      <PageHeader title="Nuevo cierre" subtitle="Carga las entradas del mes y trae los resultados del agente." />

      <Step n={1} title="Datos del mes" description="La carpeta de una fase tal como la dan los organizadores." done={!!meta}>
        <DatasetStep chosenId={chosenId} onChosen={setChosenId} />
      </Step>

      <Step n={2} title="Resultados del agente" description="De dónde salen las 6 entregas que la app revisa." done={!!activeRun} disabled={!meta}>
        {meta ? <ResultsStep meta={meta} hasRun={!!activeRun} onCreated={setCreatedId} /> : <p className={s.muted}>Carga primero los datos del mes.</p>}
      </Step>

      {activeRun && (
        <div className={s.next}>
          <div>
            <div className={s.nextTitle}>
              <CircleCheck aria-hidden /> Ejecución activa: {activeRun.label}
            </div>
            <div className={s.muted}>
              {RUN_SOURCE[activeRun.source].label} · {filesPresent(activeRun)} de 6 entregas · {formatDateTime(activeRun.createdAt)}
            </div>
          </div>
          <div className={s.actions}>
            <ButtonLink to={runPath(activeRun.id)} size="sm" variant="ghost">
              Ver ejecución
            </ButtonLink>
            <ButtonLink to="/entregables" size="sm">
              Entregables
            </ButtonLink>
            <ButtonLink to="/" size="sm" variant="primary">
              Ir al Resumen
            </ButtonLink>
          </div>
        </div>
      )}
    </Page>
  )
}
