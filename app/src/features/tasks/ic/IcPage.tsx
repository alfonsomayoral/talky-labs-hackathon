// `/tareas/intragrupo` Intragrupo: ¿qué pareja no cuadra y por qué? Process map, pair matrix and the pair sheet with both books.
import { useMemo, type CSSProperties } from 'react'
import { useSearchParams } from 'react-router'
import { CircleCheck, PanelRight } from 'lucide-react'
import { Amount, Badge, Button, DataTable, Mono, Page, PageHeader, QueryState, Section, Skeleton, StatusBadge, type Column } from '@/components'
import type { DatasetApi, DerivedRun, IcRow, RunBundle, WorkItem } from '@/domain/types'
import { IC_CAUSE_CATALOG } from '@/domain/catalog/policy'
import { useDatasetStore } from '@/data/stores'
import { effectiveDeliverables, makeToEur, useActiveRun, useDerivedRun } from '@/engine'
import { findFlowFilter, itemEurCents, JournalEntryView, MissingTaskFile, ProcessMap, useAsync, useProcessFlow } from '@/features/item/kit'
import { formatDate, formatMonth, formatNumber, formatPercent } from '@/lib/format'
import { useActiveItemId, useOpenItem } from '@/shell/useOpenItem'
import { icMatrix, interestCheck, pairBooks, pairOfItem, type BookSide, type IcMatrix } from './model'
import styles from './Ic.module.css'

export default function IcPage() {
  const { status, data, error } = useDerivedRun()
  const api = useDatasetStore((s) => s.api)
  const run = useActiveRun()
  return (
    <Page>
      <QueryState status={status} error={error}>
        {() => (data && api && run ? !run.present.ic ? <MissingTaskFile task="ic" /> : <Intercompany data={data} api={api} run={run} /> : null)}
      </QueryState>
    </Page>
  )
}

const causeLabel = (cause: string) => IC_CAUSE_CATALOG[cause as keyof typeof IC_CAUSE_CATALOG]?.label ?? cause
const pairLabel = (pair: string) => pair.replace('-', '–')

function Intercompany({ data, api, run }: { data: DerivedRun; api: DatasetApi; run: RunBundle }) {
  const { core } = api
  const items = useMemo(() => data.items.filter((it) => it.task === 'ic'), [data.items])
  const [params, setParams] = useSearchParams()
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
  const flow = useProcessFlow('ic')
  const node = params.get('nodo')
  const nodeFilter = findFlowFilter(flow, node)
  const matrix = useMemo(() => icMatrix(core.tasks.intercompany.pairs, items, (it) => itemEurCents(it, it.amount ?? 0, core)), [core, items])
  const withDiff = [...matrix.cells.values()].filter((c) => c.items.length)
  const pair = params.get('pareja') ?? withDiff[0]?.pair ?? null
  const visible = items.filter((it) => !nodeFilter || nodeFilter.items.has(it.id))
  const totalEur = withDiff.reduce((s, c) => s + c.eur, 0)

  return (
    <>
      <PageHeader
        title="Intragrupo"
        subtitle={
          <>
            {formatNumber(items.length)} {items.length === 1 ? 'diferencia' : 'diferencias'} en {withDiff.length} de {matrix.cells.size} parejas · <Amount cents={totalEur} compact /> · {formatMonth(core.tasks.close.month)}
          </>
        }
      />
      {flow && (
        <Section title={flow.title} description="Qué causa tiene cada diferencia y quién la corrige. Pulsa una rama para filtrar la lista.">
          <ProcessMap flow={flow} selectedId={node} onSelect={(f) => setParam('nodo', f?.id ?? null)} />
        </Section>
      )}
      <Section title="Parejas" description="Σ|diferencia| en EUR de cada pareja de tasks/intercompany.json. Pulsa una para ver su ficha.">
        <Matrix matrix={matrix} selected={pair} onSelect={(p) => setParam('pareja', p)} />
      </Section>
      <Section title="Diferencias" count={visible.length} description={nodeFilter ? `En «${nodeFilter.label}».` : undefined}>
        <DifferenceList items={visible} onPair={(p) => setParam('pareja', p)} />
      </Section>
      {pair && <PairSheet key={pair} pair={pair} items={matrix.cells.get(pair)?.items ?? []} api={api} run={run} />}
    </>
  )
}

// ---------------------------------------------------------------- matrix

function Matrix({ matrix, selected, onSelect }: { matrix: IcMatrix; selected: string | null; onSelect: (pair: string) => void }) {
  const { companies, cells } = matrix
  const max = Math.max(0, ...[...cells.values()].map((c) => c.eur))
  return (
    <div className={styles.matrixWrap}>
      <table className={styles.matrix}>
        <thead>
          <tr>
            <th aria-label="Sociedad" />
            {companies.slice(1).map((c) => (
              <th key={c} scope="col">
                <Mono>{c}</Mono>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {companies.slice(0, -1).map((row, i) => (
            <tr key={row}>
              <th scope="row">
                <Mono>{row}</Mono>
              </th>
              {companies.slice(1).map((col, j) => {
                if (j < i) return <td key={col} />
                const key = `${row}-${col}`
                const cell = cells.get(key)
                if (!cell) return <td key={col} className={styles.none} />
                const diff = cell.items.length > 0
                return (
                  <td key={col}>
                    <button
                      type="button"
                      className={styles.pairCell}
                      data-state={diff ? 'diff' : 'clean'}
                      aria-pressed={selected === key}
                      style={diff && max ? ({ '--heat': Math.sqrt(cell.eur / max) } as CSSProperties) : undefined}
                      onClick={() => onSelect(key)}
                      aria-label={`Pareja ${pairLabel(key)}: ${diff ? `${cell.items.length} diferencias` : 'cuadra'}`}
                    >
                      {diff ? (
                        <>
                          <span className={styles.pairCount}>{cell.items.length}</span>
                          <Amount cents={cell.eur} compact />
                        </>
                      ) : (
                        <span className={styles.clean}>
                          <CircleCheck aria-hidden /> Cuadra
                        </span>
                      )}
                    </button>
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

// ---------------------------------------------------------------- list

function DifferenceList({ items, onPair }: { items: WorkItem[]; onPair: (pair: string) => void }) {
  const openItem = useOpenItem()
  const active = useActiveItemId()
  const columns = useMemo<Column<WorkItem>[]>(
    () => [
      { id: 'pair', header: 'Pareja', width: 100, cell: (it) => <Mono>{pairLabel(pairOfItem(it))}</Mono>, sortValue: (it) => pairOfItem(it) },
      { id: 'cause', header: 'Causa', width: 'minmax(180px, 1fr)', cell: (it) => causeLabel(it.outcome), sortValue: (it) => it.outcome },
      { id: 'amount', header: 'Diferencia', width: 130, align: 'right', cell: (it) => <Amount cents={it.amount} currency={it.currency ?? 'EUR'} />, sortValue: (it) => Math.abs(it.amount ?? 0) },
      { id: 'company', header: 'Corrige', width: 80, cell: (it) => <Mono>{it.company ?? '—'}</Mono>, sortValue: (it) => it.company },
      { id: 'status', header: 'Estado', width: 140, cell: (it) => <StatusBadge status={it.status} /> },
    ],
    [],
  )
  return (
    <DataTable
      aria-label="Diferencias intragrupo"
      rows={items}
      columns={columns}
      getRowId={(it) => it.id}
      selectedId={active}
      onSelectedChange={(id) => {
        const it = items.find((x) => x.id === id)
        if (it) onPair(pairOfItem(it))
      }}
      onOpen={(it) => openItem(it.id)}
      height={Math.min(320, 34 + Math.max(items.length, 3) * 36)}
      globalKeys
    />
  )
}

// ---------------------------------------------------------------- pair sheet

function PairSheet({ pair, items, api, run }: { pair: string; items: WorkItem[]; api: DatasetApi; run: RunBundle }) {
  const { core } = api
  const openItem = useOpenItem()
  const [a, b] = pair.split('-') as [string, string]
  const month = core.tasks.close.month
  const rows = effectiveDeliverables(run).ic as IcRow[]
  const toEur = useMemo(() => makeToEur(core), [core])
  const currencyOf = useMemo(() => {
    const m = new Map(core.companies.map((c) => [c.code, c.currency]))
    return (code: string) => m.get(code) ?? 'EUR'
  }, [core.companies])
  const books = useAsync(async () => {
    const [y, m] = month.split('-').map(Number)
    const from = `${month}-01`
    const to = new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10)
    const results = await Promise.all([a, b].flatMap((company) => core.tasks.intercompany.accounts.map((account) => api.queryJournal({ company, account, from, to, limit: 2000 }))))
    const seen = new Set<string>()
    const entries = results.flatMap((r) => r.entries).filter((e) => !seen.has(e.id) && seen.add(e.id))
    return pairBooks([a, b], entries, core.tasks.intercompany.accounts, currencyOf, toEur)
  }, [api, a, b, month])
  const name = (code: string) => core.companies.find((c) => c.code === code)?.short ?? code
  const loan = core.intercompanyAgreements.loan

  return (
    <Section title={`Pareja ${pairLabel(pair)}`} description={`${name(a)} y ${name(b)}`}>
      {items.length ? (
        items.map((it) => {
          const row = rows[it.rowIndex] as (IcRow & { detail?: string; note?: string; account?: string }) | undefined
          return (
            <div key={it.id} className={styles.cause}>
              <div className={styles.causeHead}>
                <div>
                  <h3 className={styles.causeTitle}>{causeLabel(it.outcome)}</h3>
                  {row?.detail && <p className={styles.causeDetail}>{row.detail}</p>}
                </div>
                <Button size="sm" leadingIcon={<PanelRight />} onClick={() => openItem(it.id)}>
                  Abrir la partida
                </Button>
              </div>
              <dl className={styles.facts}>
                <div>
                  <dt>Diferencia</dt>
                  <dd>
                    <Amount cents={it.amount} currency={it.currency ?? 'EUR'} />
                  </dd>
                </div>
                <div>
                  <dt>Corrige</dt>
                  <dd>
                    <Mono>{it.company ?? '—'}</Mono>
                  </dd>
                </div>
                {row?.account && (
                  <div>
                    <dt>Cuentas</dt>
                    <dd>
                      <Mono>{row.account}</Mono>
                    </dd>
                  </div>
                )}
                <div>
                  <dt>Política</dt>
                  <dd>
                    <Mono>{it.policyRefs.join(' · ') || '§6'}</Mono>
                  </dd>
                </div>
              </dl>
              {it.outcome === 'INTEREST_DAY_COUNT' && books.status === 'ready' && <InterestCard check={interestCheck(loan, month, books.data)} loanId={loan.id} principal={loan.principal} rateBp={loan.rate_bp} />}
              {row?.adjustment?.length ? (
                <JournalEntryView lines={row.adjustment} company={it.company} title="Asiento corrector" />
              ) : (
                <p className={styles.muted}>{row?.note ?? 'Sin asiento corrector en esta tarea.'}</p>
              )}
            </div>
          )
        })
      ) : (
        <p className={styles.muted}>
          <CircleCheck aria-hidden className={styles.okIcon} /> Sin diferencias en esta pareja.
        </p>
      )}
      <h3 className={styles.subTitle}>Libros del mes</h3>
      <p className={styles.muted}>Movimientos de {formatMonth(month)} en cuentas intragrupo con la otra sociedad como socio, y los que replican un apunte de la otra parte con otro socio. Sin las valoraciones en divisa de cierre.</p>
      {books.status === 'loading' ? (
        <Skeleton height={200} radius="var(--radius-lg)" />
      ) : books.status === 'error' ? (
        <p className={styles.error}>{books.error}</p>
      ) : (
        <div className={styles.books}>
          {books.data.map((side) => (
            <Book key={side.company} side={side} other={side.company === a ? b : a} name={name(side.company)} />
          ))}
        </div>
      )}
    </Section>
  )
}

function InterestCard({ check, loanId, principal, rateBp }: { check: ReturnType<typeof interestCheck>; loanId: string; principal: number; rateBp: number }) {
  const off = (x: number | null) => x !== null && x !== check.expected
  return (
    <div className={styles.interest}>
      <p className={styles.formula}>
        <Mono>{loanId}</Mono>: <Amount cents={principal} /> × {formatPercent(rateBp / 10_000)} × {check.days}/360 = <Amount cents={check.expected} /> <span className={styles.muted}>(act/360)</span>
        <br />
        Con 30/360 serían <Amount cents={check.thirty} />.
      </p>
      <dl className={styles.facts}>
        <div>
          <dt>Prestamista registró</dt>
          <dd>
            <Amount cents={check.lender} /> {off(check.lender) && <Badge tone="warn">≠ act/360</Badge>}
          </dd>
        </div>
        <div>
          <dt>Prestatario registró</dt>
          <dd>
            <Amount cents={check.borrower} /> {off(check.borrower) && <Badge tone="warn">≠ act/360</Badge>}
          </dd>
        </div>
        {check.lender !== null && check.borrower !== null && (
          <div>
            <dt>Diferencia</dt>
            <dd>
              <Amount cents={check.lender - check.borrower} signed />
            </dd>
          </div>
        )}
      </dl>
    </div>
  )
}

function Book({ side, other, name }: { side: BookSide; other: string; name: string }) {
  return (
    <div className={styles.book}>
      <div className={styles.bookHead}>
        <Mono>{side.company}</Mono> {name}
      </div>
      {side.lines.length ? (
        <table className={styles.table}>
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Cuenta</th>
              <th>Referencia</th>
              <th className={styles.num}>EUR</th>
            </tr>
          </thead>
          <tbody>
            {side.lines.map((l, i) => (
              <tr key={`${l.entry}#${i}`} title={l.text || undefined}>
                <td>{formatDate(l.date)}</td>
                <td>
                  <Mono>{l.account}</Mono>
                  {l.wrongPartner && (
                    <Badge tone="danger" className={styles.partnerBadge}>
                      socio {l.partner ?? '—'}
                    </Badge>
                  )}
                </td>
                <td>
                  <Mono>{l.reference}</Mono>
                </td>
                <td className={styles.num}>
                  <Amount cents={l.eur} signed />
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            {side.totals.map((t) => (
              <tr key={t.account}>
                <td colSpan={3}>
                  Neto <Mono>{t.account}</Mono> con {other}
                </td>
                <td className={styles.num}>
                  <Amount cents={t.eur} signed />
                </td>
              </tr>
            ))}
          </tfoot>
        </table>
      ) : (
        <p className={styles.muted}>Sin movimientos con {other} este mes.</p>
      )}
    </div>
  )
}
