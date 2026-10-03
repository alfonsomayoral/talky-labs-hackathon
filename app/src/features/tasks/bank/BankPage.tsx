// `/tareas/bancos` Conciliación bancaria: ¿cuadra cada cuenta? Grid of the accounts in tasks/bank_accounts.json.
import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router'
import { Amount, Badge, Mono, Page, PageHeader, ProgressBar, QueryState, Section } from '@/components'
import type { BankRecRow, DatasetApi, DerivedRun, RunBundle } from '@/domain/types'
import { useDatasetStore } from '@/data/stores'
import { useActiveRun, useDerivedRun } from '@/engine'
import { findFlowFilter, ProcessMap, useProcessFlow } from '@/features/item/kit'
import { formatNumber } from '@/lib/format'
import { ACCOUNT_STATUS, accountSummary, type AccountSummary } from './model'
import styles from './Bank.module.css'

export default function BankPage() {
  const { status, data, error } = useDerivedRun()
  const api = useDatasetStore((s) => s.api)
  const run = useActiveRun()
  return (
    <Page>
      <QueryState status={status} error={error}>
        {() => (data && api && run ? <BankGrid data={data} api={api} run={run} /> : null)}
      </QueryState>
    </Page>
  )
}

function useAccountSummaries(data: DerivedRun, api: DatasetApi, run: RunBundle): AccountSummary[] {
  return useMemo(() => {
    const rows = run.deliverables.bank_rec as BankRecRow[]
    const ids = api.core.tasks.bank_accounts.length ? api.core.tasks.bank_accounts : api.core.bankAccounts.map((a) => a.id)
    return ids.flatMap((id) => {
      const account = api.core.bankAccounts.find((a) => a.id === id)
      if (!account) return []
      const statement = api.core.bankStatements.find((s) => s.account === id && s.month === api.meta.month) ?? null
      return [accountSummary(account, rows.find((r) => r.account === id) ?? null, statement, data.items)]
    })
  }, [data.items, api, run])
}

const NODE_PARAM = 'nodo'

function BankGrid({ data, api, run }: { data: DerivedRun; api: DatasetApi; run: RunBundle }) {
  const accounts = useAccountSummaries(data, api, run)
  const [params, setParams] = useSearchParams()
  const node = params.get(NODE_PARAM)
  const flow = useProcessFlow('bank_rec')
  const nodeFilter = findFlowFilter(flow, node)
  const nodeAccounts = useMemo(
    () => (nodeFilter ? new Set(data.items.filter((it) => it.task === 'bank_rec' && nodeFilter.items.has(it.id)).map((it) => it.key.slice(0, it.key.indexOf('/')))) : null),
    [data.items, nodeFilter],
  )
  const visible = nodeAccounts ? accounts.filter((a) => nodeAccounts.has(a.account.id)) : accounts
  const selectNode = (id: string | null) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        if (id) next.set(NODE_PARAM, id)
        else next.delete(NODE_PARAM)
        return next
      },
      { replace: true, preventScrollReset: true },
    )
  const reconciled = accounts.filter((a) => a.status === 'reconciled').length
  const adjustments = accounts.reduce((s, a) => s + a.adjustments, 0)

  return (
    <>
      <PageHeader
        title="Conciliación bancaria"
        subtitle={`${reconciled} de ${accounts.length} cuentas conciliadas · ${formatNumber(adjustments)} asientos de ajuste`}
      />
      {flow && (
        <Section title="Mapa de decisión" description="Cuántas líneas tomaron cada camino de la política. Pulsa una rama para ver solo las cuentas que la tienen.">
          <ProcessMap flow={flow} selectedId={node} onSelect={(f) => selectNode(f?.id ?? null)} />
        </Section>
      )}

      <Section
        title="Cuentas"
        count={visible.length}
        description={nodeFilter ? `Cuentas con partidas en «${nodeFilter.label}».` : 'Saldo del extracto al cierre, líneas casadas y lo que queda abierto sin ajuste.'}
      >
        <ul className={styles.grid}>
          {visible.map((a) => (
            <li key={a.account.id}>
              <AccountCard summary={a} />
            </li>
          ))}
        </ul>
      </Section>
    </>
  )
}

function AccountCard({ summary: a }: { summary: AccountSummary }) {
  const st = ACCOUNT_STATUS[a.status]
  return (
    <Link to={`/tareas/bancos/${encodeURIComponent(a.account.id)}`} className={styles.accountCard}>
      <span className={styles.cardTop}>
        <Mono>{a.account.id}</Mono>
        <Badge tone={st.tone} variant="outline" dot>
          {st.label}
        </Badge>
      </span>
      <span className={styles.cardBank}>
        {a.account.bank} · {a.account.company} · <Mono muted>{a.account.gl_account}</Mono> · {a.account.statement_format.toUpperCase()}
      </span>
      <span className={styles.cardBalance}>
        <span className={styles.cardLabel}>Saldo del extracto</span>
        <Amount cents={a.closing} currency={a.account.currency} />
      </span>
      <ProgressBar
        size="sm"
        label={`Líneas casadas de ${a.account.id}`}
        segments={[
          { value: a.matchedBankLines, tone: 'ok', label: 'Casadas' },
          { value: Math.max(0, a.statementLines - a.matchedBankLines), tone: 'neutral', label: 'Sin casar' },
        ]}
      />
      <span className={styles.cardStats}>
        <span>
          <b className="tabular">{formatNumber(a.matchedBankLines)}</b>/{formatNumber(a.statementLines)} líneas casadas
        </span>
        <span>
          <b className="tabular">{formatNumber(a.unmatchedBank + a.unmatchedBook)}</b> sin casar
        </span>
        <span>
          <b className="tabular">{formatNumber(a.adjustments)}</b> ajustes
        </span>
      </span>
      {a.open > 0 && (
        <span className={styles.cardOpen}>
          {formatNumber(a.open)} abiertas sin ajuste · <Amount cents={a.openAmount} currency={a.account.currency} />
        </span>
      )}
    </Link>
  )
}
