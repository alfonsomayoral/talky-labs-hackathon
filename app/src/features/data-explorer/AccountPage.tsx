// `/datos/cuentas/:account`: an account of the chart with its recorded balance per company and its entries.
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { BookOpen } from 'lucide-react'
import { Amount, ButtonLink, DataTable, Mono, Page, Section, Skeleton } from '@/components'
import type { TrialBalanceRow } from '@/domain/types'
import { formatNumber } from '@/lib/format'
import { DetailHeader, Facts, NotFound, tableHeight, useApi, useCompanyCurrency } from './common'
import { useJournal, useJournalColumns } from './JournalPage'
import { dataPath } from './model'
import styles from './DataExplorer.module.css'

export function AccountPage() {
  const { account = '' } = useParams()
  const api = useApi()
  const navigate = useNavigate()
  const currency = useCompanyCurrency(api.core)
  const chart = api.core.chartOfAccounts.find((a) => a.account === account)
  const filters = useMemo(() => ({ account }), [account])
  const journal = useJournal(api, filters)
  const columns = useJournalColumns()
  const [balances, setBalances] = useState<TrialBalanceRow[] | null>(null)

  useEffect(() => {
    let alive = true
    api.recordedTrialBalance().then((rows) => alive && setBalances(rows.filter((r) => r.account === account)))
    return () => {
      alive = false
    }
  }, [api, account])

  if (!chart) return <NotFound what={`La cuenta ${account} no está en el plan de cuentas`} />
  return (
    <Page>
      <DetailHeader
        crumbs={[{ label: 'Datos', to: '/datos' }, { label: 'Plan de cuentas', to: '/datos/maestros/cuentas' }, { label: account }]}
        title={chart.description}
        subtitle={<Mono>{account}</Mono>}
        actions={
          <ButtonLink to={dataPath.journal({ account })} leadingIcon={<BookOpen />}>
            Abrir en el diario
          </ButtonLink>
        }
      />
      <Facts
        items={[
          { label: 'Tipo', value: chart.type },
          { label: 'Partidas abiertas', value: chart.open_items ? 'Sí' : 'No' },
        ]}
      />
      <Section title="Saldo registrado por sociedad" description="Σ debe − Σ haber de todo el diario cargado, en la moneda de cada sociedad.">
        {!balances ? (
          <Skeleton height={72} radius="var(--radius-lg)" />
        ) : balances.length ? (
          <div className={styles.balances}>
            {balances.map((b) => (
              <div key={b.company} className={styles.balance}>
                <Mono muted>{b.company}</Mono>
                <Amount cents={b.balance} currency={currency(b.company)} />
              </div>
            ))}
          </div>
        ) : (
          <p className={styles.muted}>Sin saldo en ninguna sociedad.</p>
        )}
      </Section>
      <Section title="Asientos" count={journal.status === 'ready' ? journal.total : undefined} description={journal.status === 'ready' && journal.total > journal.entries.length ? `Se muestran los primeros ${formatNumber(journal.entries.length)}; el resto, en el diario.` : undefined}>
        <DataTable aria-label={`Asientos de ${account}`} rows={journal.entries} columns={columns} getRowId={(e) => e.id} onOpen={(e) => navigate(dataPath.entry(e.id))} height={tableHeight(journal.entries.length, 480)} />
      </Section>
    </Page>
  )
}
