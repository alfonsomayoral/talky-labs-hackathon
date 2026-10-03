// `/tareas/bancos/:account` Conciliación de una cuenta: bank and book face to face, what is left and why,
// the adjustments, the balance bridge and the raw statement record.
import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router'
import { ArrowUpRight, Landmark } from 'lucide-react'
import clsx from 'clsx'
import { Amount, Badge, Button, EmptyState, Mono, Page, PageHeader, QueryState, Section, SegmentedControl, Skeleton } from '@/components'
import type { BankAccount, BankRecRow, DatasetApi, DerivedRun, RunBundle } from '@/domain/types'
import { useDatasetStore } from '@/data/stores'
import { useActiveRun, useDerivedRun } from '@/engine'
import { JournalEntryView, RawBankRecord } from '@/features/item/kit'
import { formatNumber } from '@/lib/format'
import { useOpenItem } from '@/shell/useOpenItem'
import { ACCOUNT_STATUS, accountSummary, adjustmentsOf, balanceBridge, glAdjustments, itemByLine, recView, unmatchedByCategory, type RecLine } from './model'
import { RecFaceView } from './RecFaceView'
import { useAccountData } from './useAccountData'
import styles from './Bank.module.css'

export default function BankAccountPage() {
  const { status, data, error } = useDerivedRun()
  const api = useDatasetStore((s) => s.api)
  const run = useActiveRun()
  const { account: id = '' } = useParams()
  return (
    <Page>
      <QueryState status={status} error={error}>
        {() => {
          if (!data || !api || !run) return null
          const account = api.core.bankAccounts.find((a) => a.id === id)
          if (!account)
            return (
              <EmptyState
                icon={<Landmark />}
                title={`No existe la cuenta ${id}`}
                action={
                  <Link to="/tareas/bancos" className={styles.back}>
                    Volver a bancos
                  </Link>
                }
              />
            )
          return <AccountRec key={account.id} data={data} api={api} run={run} account={account} />
        }}
      </QueryState>
    </Page>
  )
}

type Show = 'all' | 'matched' | 'unmatched'

function AccountRec({ data, api, run, account }: { data: DerivedRun; api: DatasetApi; run: RunBundle; account: BankAccount }) {
  const row = useMemo(() => (run.deliverables.bank_rec as BankRecRow[]).find((r) => r.account === account.id) ?? null, [run, account.id])
  const statement = useMemo(() => api.core.bankStatements.find((s) => s.account === account.id && s.month === api.meta.month) ?? null, [api, account.id])
  const summary = useMemo(() => accountSummary(account, row, statement, data.items, run.deliverables.bank_rec as BankRecRow[]), [account, row, statement, data.items, run])
  const acc = useAccountData(api, account, row)
  const cur = account.currency
  /** Adjusting entries are in the company's currency (MXN for the 3100 USD account). */
  const adjCurrency = api.core.companies.find((c) => c.code === account.company)?.currency ?? cur
  const openItem = useOpenItem()
  const [selected, setSelected] = useState<RecLine | null>(null)
  const [show, setShow] = useState<Show>('all')

  const view = useMemo(() => (row && acc.status === 'ready' ? recView(row, statement?.lines ?? [], acc.monthBook, acc.referencedBook) : null), [row, acc, statement])
  const adjustments = useMemo(() => (row ? adjustmentsOf(row, account.gl_account) : []), [row, account.gl_account])
  const onGl = useMemo(() => glAdjustments(run.deliverables.bank_rec as BankRecRow[], account.company, account.gl_account), [run, account])
  const categories = useMemo(() => (view ? unmatchedByCategory(view, onGl, adjCurrency === cur) : []), [view, onGl, adjCurrency, cur])
  const fromOthers = onGl.filter((a) => a.account !== account.id)
  const bridge = useMemo(
    () =>
      view
        ? balanceBridge({
            statementOpening: statement?.opening ?? null,
            statementClosing: statement?.closing ?? null,
            statementMovement: (statement?.lines ?? []).reduce((s, l) => s + l.amount, 0),
            glClosing: acc.glClosing,
            glMovement: acc.glMovement,
            view,
            adjustments: adjCurrency === cur ? onGl : null,
          })
        : [],
    [view, statement, acc, onGl, adjCurrency, cur],
  )
  const itemOf = useMemo(() => itemByLine(data.items, account.id), [data.items, account.id])
  const blocks = useMemo(() => (view ? view.blocks.filter((b) => show === 'all' || (show === 'matched') === (b.kind === 'match')) : []), [view, show])
  const st = ACCOUNT_STATUS[summary.status]
  const selectedItem = selected ? itemOf.get(selected.id) : undefined

  return (
    <>
      <PageHeader
        breadcrumb={
          <Link to="/tareas/bancos" className={styles.back}>
            Bancos
          </Link>
        }
        title={
          <span className={styles.titleRow}>
            <Mono>{account.id}</Mono> {account.bank}
            <Badge tone={st.tone} variant="outline" dot>
              {st.label}
            </Badge>
          </span>
        }
        subtitle={
          <>
            Sociedad {account.company} · cuenta <Mono muted>{account.gl_account}</Mono> · {cur} · extracto {account.statement_format.toUpperCase()} ·{' '}
            {formatNumber(summary.matchedBankLines)}/{formatNumber(summary.statementLines)} líneas casadas
          </>
        }
      />

      {!row ? (
        <EmptyState icon={<Landmark />} title="Esta cuenta no está en bank_rec.jsonl" description="La ejecución no trae conciliación para esta cuenta: puntúa 0 en bancos." />
      ) : acc.status === 'error' ? (
        <EmptyState icon={<Landmark />} title="No se pudo leer el diario de la cuenta" description={acc.error} />
      ) : (
        <>
          <div className={styles.topSplit}>
            <Section title="Puente de saldo" description="Del saldo del extracto al saldo contable de la 572, y después de los ajustes.">
              {!view ? (
                <Skeleton lines={7} />
              ) : (
                <ol className={styles.bridge}>
                  {bridge.map((s) => (
                    <li key={s.id} className={clsx(styles.bridgeRow, s.kind === 'total' && styles.bridgeTotal, s.id === 'gap' && styles.bridgeGap)}>
                      <span>
                        {s.label}
                        {s.detail && <span className={styles.bridgeDetail}>{s.detail}</span>}
                      </span>
                      <Amount cents={s.amount} currency={cur} signed={s.kind === 'step'} />
                    </li>
                  ))}
                </ol>
              )}
            </Section>

            <Section title="Sin casar por categoría" count={categories.reduce((s, c) => s + c.lines.length, 0)}>
              {!view ? (
                <Skeleton lines={4} />
              ) : categories.length === 0 ? (
                <p className={styles.muted}>Todas las líneas del mes están casadas.</p>
              ) : (
                <ul className={styles.categories}>
                  {categories.map((c) => (
                    <li key={c.category} className={styles.category}>
                      <span className={styles.categoryHead}>
                        <span className={styles.categoryLabel}>{c.label}</span>
                        {c.section && <Mono muted>{c.section}</Mono>}
                        <Badge tone={c.adjusted ? (c.uncovered ? 'danger' : 'ok') : c.expectsAdjustment ? 'danger' : 'neutral'} variant="outline" dot>
                          {c.adjusted ? (
                            c.uncovered ? (
                              <>
                                Falta ajuste por <Amount cents={c.uncovered} currency={cur} />
                              </>
                            ) : (
                              'Con ajuste'
                            )
                          ) : c.expectsAdjustment ? (
                            'Falta el ajuste'
                          ) : (
                            'Sin ajuste: queda abierta'
                          )}
                        </Badge>
                        <span className={styles.categoryAmount}>
                          <Amount cents={c.amount} currency={cur} />
                        </span>
                      </span>
                      <span className={styles.categoryLines}>
                        {c.lines.map((l) => (
                          <button key={l.id} type="button" className={clsx(styles.chipLine, selected?.id === l.id && styles.chipSelected)} onClick={() => setSelected(l)}>
                            {l.id}
                          </button>
                        ))}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>

          <Section
            title="Extracto frente a libro"
            count={view?.groups.length}
            description="Cada casación une sus líneas del extracto con sus apuntes de la 572 (1:1, N:1 o 1:N). Pulsa una línea para ver su registro."
            actions={
              <SegmentedControl
                aria-label="Mostrar"
                size="sm"
                value={show}
                onChange={(v) => setShow(v as Show)}
                options={[
                  { value: 'all', label: 'Todo' },
                  { value: 'matched', label: 'Casadas' },
                  { value: 'unmatched', label: 'Sin casar' },
                ]}
              />
            }
          >
            {!view ? <Skeleton lines={10} /> : <RecFaceView blocks={blocks} currency={cur} selectedId={selected?.id ?? null} onSelect={setSelected} />}
            {view && (view.untreatedBank.length > 0 || view.untreatedBook.length > 0) && (
              <p className={styles.warnNote}>
                {view.untreatedBank.length} líneas del extracto y {view.untreatedBook.length} apuntes del mes no figuran en la conciliación:{' '}
                {[...view.untreatedBank, ...view.untreatedBook].map((l) => l.id).join(', ')}
              </p>
            )}
          </Section>

          <div className={styles.topSplit}>
            <Section title="Registro del extracto" description={`Original ${account.statement_format.toUpperCase()} de la línea elegida.`}>
              {!selected ? (
                <p className={styles.muted}>Elige una línea del extracto.</p>
              ) : (
                <div className={styles.raw}>
                  <span className={styles.titleRow}>
                    <Mono>{selected.id}</Mono>
                    <Amount cents={selected.amount} currency={cur} colorize />
                    {selectedItem && (
                      <Button size="sm" variant="ghost" trailingIcon={<ArrowUpRight />} onClick={() => openItem(selectedItem)}>
                        Abrir partida
                      </Button>
                    )}
                  </span>
                  {selected.side === 'book' ? (
                    <p className={styles.muted}>Es un apunte del libro: su asiento se ve en la partida.</p>
                  ) : (
                    <RawBankRecord bankLine={selected.id} />
                  )}
                </div>
              )}
            </Section>

            <Section title="Ajustes" count={adjustments.length} description="Asientos que propone la conciliación; su efecto en la 572 entra en el puente.">
              {fromOthers.map((a) => (
                <p key={`${a.account}-${a.index}`} className={styles.muted}>
                  Desde <Link to={`/tareas/bancos/${encodeURIComponent(a.account)}`}>{a.account}</Link>: {a.label} mueve esta 572 en{' '}
                  <Amount cents={a.glMovement} currency={adjCurrency} signed />.
                </p>
              ))}
              {adjustments.length === 0 ? (
                <p className={styles.muted}>Sin ajustes propios.</p>
              ) : (
                <ul className={styles.adjustments}>
                  {adjustments.map((a) => (
                    <li key={a.index} className={styles.adjustment}>
                      <span className={styles.categoryHead}>
                        <span className={styles.categoryLabel}>{a.label}</span>
                        <span className={styles.categoryAmount}>
                          572 <Amount cents={a.glMovement} currency={adjCurrency} signed />
                        </span>
                      </span>
                      <JournalEntryView lines={a.lines} company={account.company} currency={adjCurrency} />
                    </li>
                  ))}
                </ul>
              )}
            </Section>
          </div>
        </>
      )}
    </>
  )
}
