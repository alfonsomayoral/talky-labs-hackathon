// Dev page (/dev/data): load datasets through every source, inspect the inventory, check the
// recorded trial balance against golden, create/import runs and peek at useDerivedRun().
import { useEffect, useState, type DragEvent, type ReactNode } from 'react'
import type { JournalEntry, TrialBalanceRow } from '@/domain/types'
import { useDerivedRun } from '@/engine/useDerivedRun'
import { filesFromDataTransfer, useDatasetStore, useRunStore } from '../stores'
import s from './DataDebugPage.module.css'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const mb = (bytes: number) => `${(bytes / 1024 / 1024).toFixed(1)} MB`

function Box({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className={s.box}>
      <h2>{title}</h2>
      {children}
    </section>
  )
}

function FolderInput({ label, onFiles }: { label: string; onFiles: (files: File[]) => void }) {
  return (
    <label className={s.button} style={{ display: 'inline-flex', alignItems: 'center' }}>
      {label}
      <input
        type="file"
        multiple
        hidden
        ref={(el) => {
          if (el) el.webkitdirectory = true
        }}
        onChange={(e) => {
          const files = [...(e.target.files ?? [])]
          e.target.value = ''
          if (files.length) onFiles(files)
        }}
      />
    </label>
  )
}

function FileInput({ label, accept, multiple, onFiles }: { label: string; accept: string; multiple?: boolean; onFiles: (files: File[]) => void }) {
  return (
    <label className={s.button} style={{ display: 'inline-flex', alignItems: 'center' }}>
      {label}
      <input
        type="file"
        accept={accept}
        multiple={multiple}
        hidden
        onChange={(e) => {
          const files = [...(e.target.files ?? [])]
          e.target.value = ''
          if (files.length) onFiles(files)
        }}
      />
    </label>
  )
}

type DirectoryPicker = () => Promise<FileSystemDirectoryHandle>

function TrialBalanceCheck() {
  const api = useDatasetStore((st) => st.api)
  const [result, setResult] = useState<{ rows: number; ms: number; diffs: number | null; sample: string[] } | { error: string } | null>(null)
  useEffect(() => setResult(null), [api])
  if (!api) return null
  const run = async () => {
    setResult(null)
    const t = performance.now()
    try {
      const tb = await api.recordedTrialBalance()
      const ms = Math.round(performance.now() - t)
      const golden = api.core.golden?.trialBalanceRecorded
      if (!golden) return setResult({ rows: tb.length, ms, diffs: null, sample: [] })
      const key = (r: TrialBalanceRow) => `${r.company}/${r.account}`
      const mine = new Map(tb.map((r) => [key(r), r.balance]))
      const gold = new Map(golden.map((r) => [key(r), r.balance]))
      const diffs = [...new Set([...mine.keys(), ...gold.keys()])].filter((k) => mine.get(k) !== gold.get(k))
      setResult({ rows: tb.length, ms, diffs: diffs.length, sample: diffs.slice(0, 10).map((k) => `${k}: ${mine.get(k) ?? '—'} ≠ ${gold.get(k) ?? '—'}`) })
    } catch (e) {
      setResult({ error: message(e) })
    }
  }
  return (
    <div className={s.row}>
      <button className={s.button} onClick={run}>
        Comprobar balance registrado
      </button>
      {result && 'error' in result && <span className={s.error}>{result.error}</span>}
      {result && 'rows' in result && (
        <span>
          {result.rows} filas en {result.ms} ms ·{' '}
          {result.diffs === null ? (
            'sin golden para comparar'
          ) : result.diffs === 0 ? (
            <b className={s.ok}>coincide con golden/trial_balance_recorded.jsonl</b>
          ) : (
            <b className={s.error}>
              {result.diffs} diferencias: {result.sample.join('; ')}
            </b>
          )}
        </span>
      )}
    </div>
  )
}

function JournalProbe() {
  const api = useDatasetStore((st) => st.api)
  const [account, setAccount] = useState('57200001')
  const [company, setCompany] = useState('')
  const [result, setResult] = useState<{ total: number; entries: JournalEntry[]; ms: number } | { error: string } | null>(null)
  if (!api) return null
  const run = async () => {
    const t = performance.now()
    try {
      const r = await api.queryJournal({ account: account || undefined, company: company || undefined, limit: 5 })
      setResult({ ...r, ms: Math.round(performance.now() - t) })
    } catch (e) {
      setResult({ error: message(e) })
    }
  }
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      <div className={s.row}>
        <input className={s.mono} value={account} onChange={(e) => setAccount(e.target.value)} placeholder="cuenta" aria-label="Cuenta" />
        <input className={s.mono} value={company} onChange={(e) => setCompany(e.target.value)} placeholder="sociedad" aria-label="Sociedad" />
        <button className={s.button} onClick={run}>
          Consultar diario
        </button>
        {result && 'error' in result && <span className={s.error}>{result.error}</span>}
        {result && 'total' in result && (
          <span>
            {result.total} asientos ({result.ms} ms)
          </span>
        )}
      </div>
      {result && 'entries' in result && result.entries.length > 0 && (
        <pre className={s.pre}>{result.entries.map((e) => `${e.id}  ${e.posting_date}  ${e.source.padEnd(14)} ${e.header_text}`).join('\n')}</pre>
      )}
    </div>
  )
}

export default function DataDebugPage() {
  const ds = useDatasetStore()
  const runs = useRunStore()
  const derived = useDerivedRun()
  const [dragging, setDragging] = useState(false)
  const [remote, setRemote] = useState<{ id: string; label: string; source: string }[] | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const meta = ds.api?.meta ?? null

  useEffect(() => {
    void useDatasetStore.getState().refreshAvailable()
  }, [])

  const attempt = (fn: () => Promise<unknown>) => () => {
    setActionError(null)
    fn().catch((e: unknown) => setActionError(message(e)))
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    const pending = filesFromDataTransfer(e.dataTransfer)
    attempt(async () => {
      const files = await pending
      if (files.length === 1 && files[0].name.toLowerCase().endsWith('.zip')) await ds.loadFromZip(files[0])
      else await ds.loadFromFolder(files)
    })()
  }

  const picker = (window as unknown as { showDirectoryPicker?: DirectoryPicker }).showDirectoryPicker

  return (
    <div className={s.page}>
      <h1 className={s.title}>Datos (depuración)</h1>

      <Box title="Cargar dataset">
        <div className={s.row}>
          <span className={s.label}>Servidos en desarrollo:</span>
          {ds.available.length === 0 && <span className={s.label}>ninguno (revisa KALMORA_DATASETS)</span>}
          {ds.available.map((a) => (
            <button key={`${a.source}:${a.id}`} className={s.button} onClick={attempt(() => ds.loadFromHttp(a.id))}>
              {a.name} <span className={s.label}>({a.source}:{a.id})</span>
            </button>
          ))}
        </div>
        <div className={s.row}>
          <FolderInput label="Elegir carpeta…" onFiles={(files) => attempt(() => ds.loadFromFolder(files))()} />
          {picker && (
            <button className={s.button} onClick={attempt(async () => ds.loadFromFolder(await picker()))}>
              Elegir carpeta (acceso persistente)…
            </button>
          )}
          <FileInput label="Elegir zip…" accept=".zip" onFiles={(files) => attempt(() => ds.loadFromZip(files[0]))()} />
        </div>
        <div
          className={dragging ? s.dropActive : s.drop}
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          Arrastra aquí la carpeta de una fase (o su .zip)
        </div>
        <div className={s.row}>
          <span className={s.label}>Estado:</span> <b>{ds.status}</b>
          {ds.progress && (
            <span>
              {ds.progress.phase} {ds.progress.total > 1 && `${ds.progress.done}/${ds.progress.total}`}
            </span>
          )}
          {ds.error && <span className={s.error}>{ds.error}</span>}
          {actionError && actionError !== ds.error && <span className={s.error}>{actionError}</span>}
        </div>
      </Box>

      <Box title="Datasets guardados">
        {ds.datasets.length === 0 && <span className={s.label}>Ninguno todavía.</span>}
        {ds.datasets.map((d) => (
          <div key={d.id} className={s.row}>
            <span className={s.mono}>{d.id}</span>
            <span className={s.label}>
              {d.sourceKind} · {new Date(d.loadedAt).toLocaleString('es-ES')}
            </span>
            {d.id === ds.activeId ? <b className={s.ok}>activo</b> : <button className={s.button} onClick={attempt(() => ds.activate(d.id))}>Activar</button>}
            <button className={s.button} onClick={attempt(() => ds.remove(d.id))}>
              Eliminar
            </button>
          </div>
        ))}
      </Box>

      {meta && (
        <Box title={`Inventario · ${meta.name} · ${meta.month}`}>
          <table className={s.table}>
            <tbody>
              <tr><th>Id</th><td className={s.mono}>{meta.id}{meta.remoteId && ` (remoto: ${meta.remoteId})`}</td></tr>
              <tr><th>Sociedades</th><td>{meta.inventory.companies}</td></tr>
              <tr><th>Documentos AP</th><td>{meta.inventory.apDocuments} · {Object.entries(meta.inventory.apByChannel).map(([k, v]) => `${k} ${v}`).join(' · ')}</td></tr>
              <tr><th>Partidas de facturación</th><td>{meta.inventory.arBillingItems}</td></tr>
              <tr><th>Remesas / avisos de cobro</th><td>{meta.inventory.arRemittanceFiles} ficheros · {meta.inventory.arNotices} penalidades</td></tr>
              <tr><th>Cuentas bancarias</th><td>{meta.inventory.bankAccounts} · {Object.entries(meta.inventory.statementsByFormat).map(([k, v]) => `${k} ${v}`).join(' · ')}</td></tr>
              <tr><th>Diario</th><td>{mb(meta.inventory.journalBytes)} · {meta.inventory.journalMonths[0]} → {meta.inventory.journalMonths.at(-1)} ({meta.inventory.journalMonths.length} meses)</td></tr>
              <tr><th>Golden</th><td>{meta.inventory.hasGolden ? 'sí' : 'no'}</td></tr>
              <tr><th>Ficheros</th><td>{meta.inventory.files} · {mb(meta.inventory.bytes)}</td></tr>
              <tr><th>Tareas</th><td>{ds.api && `${ds.api.core.tasks.ap_documents.length} AP · ${ds.api.core.tasks.ar_billing_items.length} facturación · ${ds.api.core.tasks.ar_receipts.length} cobros · ${ds.api.core.tasks.bank_accounts.length} bancos · ${ds.api.core.tasks.intercompany.pairs.length} parejas IC`}</td></tr>
            </tbody>
          </table>
          {meta.inventory.warnings.length > 0 ? (
            <ul className={s.warnings}>
              {meta.inventory.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          ) : (
            <span className={s.ok}>Sin avisos de estructura.</span>
          )}
          <TrialBalanceCheck />
          <JournalProbe />
        </Box>
      )}

      <Box title="Ejecuciones">
        <div className={s.row}>
          <button className={s.primary} disabled={!meta?.inventory.hasGolden} onClick={attempt(() => runs.createGoldenRun())}>
            Crear ejecución de referencia (golden)
          </button>
          <FileInput label="Importar JSONL / zip…" accept=".jsonl,.json,.zip" multiple onFiles={(files) => attempt(() => runs.importRun(files.length === 1 ? files[0] : files))()} />
          <FolderInput label="Importar carpeta de ejecución…" onFiles={(files) => attempt(() => runs.importRun(files))()} />
          <button className={s.button} onClick={attempt(async () => setRemote(await runs.listRemoteRuns()))}>
            Buscar ejecuciones remotas
          </button>
          <span className={s.label}>Estado:</span> <b>{runs.status}</b>
          {runs.error && <span className={s.error}>{runs.error}</span>}
        </div>
        {remote && (
          <div className={s.row}>
            {remote.length === 0 && <span className={s.label}>No hay ejecuciones en /__runs ni en la API.</span>}
            {remote.map((r) => (
              <button key={r.id} className={s.button} disabled={!meta} onClick={attempt(() => runs.loadRemoteRun(r.id))}>
                {r.label} <span className={s.label}>({r.source})</span>
              </button>
            ))}
          </div>
        )}
        {runs.runs.length === 0 && <span className={s.label}>Sin ejecuciones para este dataset.</span>}
        {runs.runs.map((r) => (
          <div key={r.id} className={s.row}>
            <input type="radio" name="active-run" checked={r.id === runs.activeId} onChange={() => runs.setActive(r.id)} aria-label={`Activar ${r.label}`} />
            <b>{r.label}</b>
            <span className={s.mono}>{r.id}</span>
            <span className={s.label}>
              {r.source} · {Object.entries(r.present).filter(([, v]) => v).length}/6 entregas · {Object.values(r.deliverables).reduce((n, rows) => n + rows.length, 0)} filas
              {r.events && ` · ${r.events.length} eventos`}
              {r.attention && ` · ${r.attention.length} atención`}
            </span>
            <button className={s.button} onClick={attempt(() => runs.remove(r.id))}>
              Eliminar
            </button>
          </div>
        ))}
      </Box>

      <Box title="Motor · useDerivedRun()">
        <div className={s.row}>
          <span className={s.label}>Estado:</span> <b>{derived.status}</b>
          {derived.error && <span className={s.error}>{derived.error}</span>}
          <span className={s.label}>Nota:</span> <b className={s.mono}>{derived.data?.score?.total ?? '—'}</b>
        </div>
        {derived.data?.stats && <pre className={s.pre}>{JSON.stringify(derived.data.stats, null, 2)}</pre>}
      </Box>
    </div>
  )
}
