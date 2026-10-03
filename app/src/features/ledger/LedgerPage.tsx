// `/balance` Balance de sumas y saldos: ¿cuánto falta para el balance correcto? Recorded journal + every delivered entry vs the truth.
import { useMemo, type CSSProperties, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router'
import { Amount, Button, DataTable, Metric, Mono, Page, PageHeader, QueryState, Section, SegmentedControl, Skeleton, type Column } from '@/components'
import type { Cents, DatasetCore, TaskKey, TbRow, TrialBalanceComparison } from '@/domain/types'
import { PIPELINE, TASK_LABEL } from '@/domain/catalog/labels'
import { useDatasetStore } from '@/data/stores'
import { makeToEur, useDerivedRun, type ToEur } from '@/engine'
import { formatNumber, formatPercent } from '@/lib/format'
import { ACCOUNT_GROUP_LABEL, accountGroup, gapWaterfall, heatKey, heatMap, relevantRows, remainingDiff, type GapWaterfall, type HeatMeasure } from './model'
import styles from './Ledger.module.css'

export default function LedgerPage() {
  const { status, data, error } = useDerivedRun()
  const core = useDatasetStore((s) => s.api?.core ?? null)
  return (
    <Page>
      <PageHeader
        title="Balance de sumas y saldos"
        subtitle={
          data?.trialBalance && data.trialBalance.gapRecorded === null
            ? 'Diario registrado más todos los asientos de la entrega. Sin balance correcto en este dataset: se ve cuánto mueve cada tarea.'
            : 'Diario registrado más todos los asientos de la entrega, comparado cuenta a cuenta con el balance correcto.'
        }
      />
      <QueryState status={status} error={error}>
        {() =>
          data && core ? (
            data.trialBalance ? (
              <Ledger tb={data.trialBalance} core={core} />
            ) : (
              <Skeleton height={320} radius="var(--radius-lg)" />
            )
          ) : null
        }
      </QueryState>
    </Page>
  )
}

const MEASURES: { value: HeatMeasure; label: string }[] = [
  { value: 'remaining', label: 'Hueco después' },
  { value: 'recorded', label: 'Hueco antes' },
  { value: 'movement', label: 'Movimiento' },
]

function Ledger({ tb, core }: { tb: TrialBalanceComparison; core: DatasetCore }) {
  const toEur = useMemo(() => makeToEur(core), [core])
  const golden = tb.gapRecorded !== null
  const waterfall = useMemo(() => gapWaterfall(tb, toEur), [tb, toEur])
  const [params, setParams] = useSearchParams()
  const fallback: HeatMeasure = !golden ? 'movement' : tb.gapAfter ? 'remaining' : 'recorded'
  const measure = MEASURES.find((m) => m.value === params.get('medida'))?.value ?? fallback
  const cell = params.get('celda')
  const setParam = (key: string, value: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (value) next.set(key, value)
        else next.delete(key)
        return next
      },
      { replace: true, preventScrollReset: true },
    )
  const rows = useMemo(() => relevantRows(tb.rows), [tb.rows])
  const touched = rows.filter((r) => Object.values(r.delta).some((x) => x)).length
  const movement = tb.eur ? Object.values(tb.eur.movementByTask).reduce((s, x) => s + x, 0) : null

  return (
    <>
      <div className={styles.vitals}>
        {golden ? (
          <>
            <Metric label="Hueco registrado" value={<Amount cents={tb.eur?.gapRecorded ?? null} compact />} comparison="Σ|correcto − registrado|" hint="Suma de las diferencias absolutas con el balance correcto antes de la entrega, en EUR al tipo de cierre (3100 está en MXN)." />
            <Metric label="Hueco después" value={<Amount cents={tb.eur?.gapAfter ?? null} compact />} comparison="Σ|correcto − después|" />
            <Metric
              label="Hueco cerrado"
              value={formatPercent(tb.eur?.gapRecorded ? 1 - (tb.eur.gapAfter ?? 0) / tb.eur.gapRecorded : null)}
              comparison="en EUR"
            />
            <Metric label="Nota del balance" value={formatPercent(tb.score)} comparison="score.py, en moneda local" hint="La nota del scorer suma céntimos de cada sociedad en su moneda, sin convertir: los errores de 3100 pesan unas 19 veces más." />
          </>
        ) : (
          <>
            <Metric label="Movimiento de la entrega" value={<Amount cents={movement} compact />} comparison="Σ|asientos| en EUR" />
            <Metric label="Cuentas tocadas" value={formatNumber(touched)} />
            <Metric label="Hueco" value="—" comparison="Sin balance correcto en este dataset" />
          </>
        )}
      </div>

      {waterfall ? (
        <Section
          title="Hueco cerrado por tarea"
          description="Se suman las tareas en el orden del cierre. El hueco no es aditivo: un cobro solo cuadra la 43 si antes se ha facturado, así que cada tramo depende del orden."
        >
          <Waterfall w={waterfall} />
        </Section>
      ) : (
        <Section title="Movimiento por tarea" description="Σ|asientos| de cada tarea en EUR, al tipo de cierre. Sin balance correcto (golden) no se puede medir el hueco.">
          {tb.eur ? <MovementBars byTask={tb.eur.movementByTask} /> : <p className={styles.muted}>Sin importes en EUR.</p>}
        </Section>
      )}

      <Section
        title="Dónde queda"
        description="Por sociedad y grupo del plan de cuentas, en EUR. Pulsa una celda para filtrar las cuentas."
        actions={
          <SegmentedControl
            aria-label="Medida del mapa"
            size="sm"
            options={golden ? MEASURES : MEASURES.filter((m) => m.value === 'movement')}
            value={measure}
            onChange={(v) => setParam('medida', v)}
          />
        }
      >
        <Heat rows={tb.rows} toEur={toEur} measure={measure} selected={cell} onSelect={(k) => setParam('celda', k === cell ? null : k)} core={core} />
      </Section>

      <Accounts rows={rows} core={core} toEur={toEur} cell={cell} golden={golden} sortByDiff={!!tb.gapAfter} onClearCell={() => setParam('celda', null)} />
    </>
  )
}

// ---------------------------------------------------------------- waterfall

function Waterfall({ w }: { w: GapWaterfall }) {
  const scale = Math.max(w.recorded, ...w.steps.map((s) => s.remaining)) || 1
  const pct = (x: number) => `${(x / scale) * 100}%`
  const bar = (from: number, to: number): CSSProperties => ({ left: pct(Math.min(from, to)), width: pct(Math.abs(to - from)) })
  let previous = w.recorded
  return (
    <div className={styles.waterfall} role="table" aria-label="Hueco cerrado por tarea">
      <WaterfallRow label="Registrado" style={bar(0, w.recorded)} tone="total" value={<Amount cents={w.recorded} compact />} />
      {w.steps.map((s) => {
        const style = bar(previous, s.remaining)
        previous = s.remaining
        return (
          <WaterfallRow
            key={s.task}
            label={TASK_LABEL[s.task]}
            style={style}
            tone={s.closed > 0 ? 'closed' : s.closed < 0 ? 'opened' : 'none'}
            value={s.closed ? <Amount cents={s.closed} signed colorize compact /> : <span className={styles.muted}>Sin efecto</span>}
          />
        )
      })}
      <WaterfallRow label="Después" style={bar(0, w.after)} tone="total" value={<Amount cents={w.after} compact />} />
    </div>
  )
}

function MovementBars({ byTask }: { byTask: Record<TaskKey, Cents> }) {
  const scale = Math.max(...PIPELINE.map((t) => byTask[t] ?? 0)) || 1
  return (
    <div className={styles.waterfall} role="table" aria-label="Movimiento por tarea">
      {PIPELINE.map((t) => {
        const cents = byTask[t] ?? 0
        return (
          <WaterfallRow
            key={t}
            label={TASK_LABEL[t]}
            style={{ left: 0, width: `${(cents / scale) * 100}%` }}
            tone={cents ? 'total' : 'none'}
            value={cents ? <Amount cents={cents} compact /> : <span className={styles.muted}>Sin efecto</span>}
          />
        )
      })}
    </div>
  )
}

function WaterfallRow({ label, style, tone, value }: { label: string; style: CSSProperties; tone: 'total' | 'closed' | 'opened' | 'none'; value: ReactNode }) {
  return (
    <div className={styles.wfRow} role="row">
      <span className={styles.wfLabel} role="rowheader">
        {label}
      </span>
      <span className={styles.wfTrack} role="cell">
        {tone !== 'none' && <span className={styles.wfBar} data-tone={tone} style={style} />}
      </span>
      <span className={styles.wfValue} role="cell">
        {value}
      </span>
    </div>
  )
}

// ---------------------------------------------------------------- heat map

function Heat({ rows, toEur, measure, selected, onSelect, core }: { rows: TbRow[]; toEur: ToEur; measure: HeatMeasure; selected: string | null; onSelect: (key: string) => void; core: DatasetCore }) {
  const map = useMemo(() => heatMap(rows, toEur, measure), [rows, toEur, measure])
  const name = (code: string) => core.companies.find((c) => c.code === code)?.short ?? code
  return (
    <div className={styles.heatWrap}>
      <table className={styles.heat}>
        <thead>
          <tr>
            <th scope="col">Sociedad</th>
            {map.groups.map((g) => (
              <th key={g} scope="col" title={ACCOUNT_GROUP_LABEL[g]}>
                <span className={styles.groupCode}>{g}</span>
                <span className={styles.groupName}>{ACCOUNT_GROUP_LABEL[g] ?? ''}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {map.companies.map((company) => (
            <tr key={company}>
              <th scope="row">
                <Mono>{company}</Mono> <span className={styles.companyName}>{name(company)}</span>
              </th>
              {map.groups.map((g) => {
                const k = heatKey(company, g)
                const c = map.cells.get(k)
                const heat = c && map.max ? Math.sqrt(c.eur / map.max) : 0
                return (
                  <td key={g}>
                    {c ? (
                      <button
                        type="button"
                        className={styles.heatCell}
                        data-measure={measure}
                        aria-pressed={selected === k}
                        style={{ '--heat': heat } as CSSProperties}
                        onClick={() => onSelect(k)}
                        title={`${company} · grupo ${g}: ${formatNumber(c.accounts)} cuentas`}
                      >
                        <Amount cents={c.eur} compact />
                      </button>
                    ) : (
                      <span className={styles.heatEmpty}>—</span>
                    )}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------- accounts

function Accounts({ rows, core, toEur, cell, golden, sortByDiff, onClearCell }: { rows: TbRow[]; core: DatasetCore; toEur: ToEur; cell: string | null; golden: boolean; sortByDiff: boolean; onClearCell: () => void }) {
  const navigate = useNavigate()
  const names = useMemo(() => new Map(core.chartOfAccounts.map((a) => [a.account, a.description])), [core.chartOfAccounts])
  const currency = useMemo(() => {
    const map = new Map(core.companies.map((c) => [c.code, c.currency]))
    return (company: string) => map.get(company) ?? 'EUR'
  }, [core.companies])
  const visible = useMemo(() => (cell ? rows.filter((r) => heatKey(r.company, accountGroup(r.account)) === cell) : rows), [rows, cell])
  const columns = useMemo<Column<TbRow>[]>(() => {
    const money = (cents: number | null, r: TbRow, opts: { colorize?: boolean } = {}) => <Amount cents={cents} currency={currency(r.company)} signed={opts.colorize} colorize={opts.colorize} hideCurrency />
    const eur = (r: TbRow, cents: number | null) => (cents === null ? null : toEur(r.company, cents))
    const cols: Column<TbRow>[] = [
      { id: 'company', header: 'Soc.', width: 72, cell: (r) => <Mono>{r.company}</Mono>, sortValue: (r) => r.company },
      { id: 'account', header: 'Cuenta', width: 96, cell: (r) => <Mono>{r.account}</Mono>, sortValue: (r) => r.account },
      {
        id: 'name',
        header: 'Descripción',
        width: 'minmax(140px, 1fr)',
        cell: (r) => {
          const name = names.get(r.account)
          return name ? (
            <span className={styles.ellipsis} title={name}>
              {name}
            </span>
          ) : (
            '—'
          )
        },
      },
      { id: 'currency', header: 'Moneda', width: 76, cell: (r) => <Mono muted>{currency(r.company)}</Mono> },
      { id: 'recorded', header: 'Registrado', width: 140, align: 'right', cell: (r) => money(r.recorded, r), sortValue: (r) => eur(r, r.recorded) },
      { id: 'movement', header: 'Entrega', width: 140, align: 'right', cell: (r) => (r.after !== r.recorded ? money(r.after - r.recorded, r, { colorize: true }) : null), sortValue: (r) => Math.abs(toEur(r.company, r.after - r.recorded)) },
      { id: 'after', header: 'Después', width: 140, align: 'right', cell: (r) => money(r.after, r), sortValue: (r) => eur(r, r.after) },
    ]
    if (golden)
      cols.push(
        { id: 'truth', header: 'Correcto', width: 140, align: 'right', cell: (r) => money(r.truth, r), sortValue: (r) => eur(r, r.truth) },
        {
          id: 'diff',
          header: 'Diferencia',
          width: 140,
          align: 'right',
          cell: (r) => {
            const d = remainingDiff(r)
            return d ? money(d, r, { colorize: true }) : <span className={styles.ok}>Cuadra</span>
          },
          sortValue: (r) => Math.abs(toEur(r.company, remainingDiff(r) ?? 0)),
        },
      )
    return cols
  }, [names, currency, toEur, golden])
  return (
    <Section
      title="Cuentas"
      count={visible.length}
      description={
        cell
          ? `Grupo ${cell.split('/')[1]} de ${cell.split('/')[0]}.`
          : golden
            ? 'Cuentas que toca la entrega o que no cuadran con el balance correcto, en la moneda de cada sociedad.'
            : 'Cuentas que toca la entrega, en la moneda de cada sociedad.'
      }
      actions={
        cell ? (
          <Button size="sm" variant="ghost" onClick={onClearCell}>
            Ver todas
          </Button>
        ) : undefined
      }
    >
      <DataTable
        aria-label="Cuentas del balance"
        rows={visible}
        columns={columns}
        getRowId={(r) => `${r.company}/${r.account}`}
        defaultSort={{ columnId: sortByDiff ? 'diff' : 'movement', direction: 'desc' }}
        onOpen={(r) => navigate(`/datos/cuentas/${encodeURIComponent(r.account)}`)}
        height={520}
        globalKeys
      />
    </Section>
  )
}
