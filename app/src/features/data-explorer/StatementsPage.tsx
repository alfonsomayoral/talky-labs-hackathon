// `/datos/extractos`: bank statements per account and month, each line with its raw record and the items it feeds.
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router'
import { PanelRight } from 'lucide-react'
import { Amount, Button, DataTable, Mono, Page, PageHeader, Section, Skeleton, StatusBadge, type Column } from '@/components'
import type { BankLine, BankStatement, RawBankDetail } from '@/domain/types'
import { formatDate, formatMonth, formatNumber } from '@/lib/format'
import { useOpenItem } from '@/shell/useOpenItem'
import { DetailHeader, Facts, NotFound, SectionTabs, tableHeight, TextLink, useApi, useRunItems } from './common'
import { bankLineItems, dataPath, fileName } from './model'
import styles from './DataExplorer.module.css'

const FORMAT_LABEL: Record<BankStatement['format'], string> = { n43: 'Norma 43', camt053: 'CAMT.053', csv: 'CSV' }

export function StatementsPage() {
  const { core } = useApi()
  const navigate = useNavigate()
  const accounts = useMemo(() => new Map(core.bankAccounts.map((a) => [a.id, a])), [core.bankAccounts])
  const columns = useMemo<Column<BankStatement>[]>(() => {
    const currency = (s: BankStatement) => accounts.get(s.account)?.currency ?? s.lines[0]?.currency ?? 'EUR'
    return [
      { id: 'account', header: 'Cuenta', width: 150, cell: (s) => <Mono>{s.account}</Mono>, sortValue: (s) => s.account },
      { id: 'company', header: 'Sociedad', width: 80, cell: (s) => <Mono>{accounts.get(s.account)?.company ?? '—'}</Mono>, sortValue: (s) => accounts.get(s.account)?.company },
      { id: 'bank', header: 'Banco', width: 'minmax(160px, 1fr)', cell: (s) => accounts.get(s.account)?.bank, sortValue: (s) => accounts.get(s.account)?.bank },
      { id: 'format', header: 'Formato', width: 100, cell: (s) => FORMAT_LABEL[s.format], sortValue: (s) => s.format },
      { id: 'month', header: 'Mes', width: 120, cell: (s) => formatMonth(s.month), sortValue: (s) => s.month },
      { id: 'lines', header: 'Líneas', width: 80, align: 'right', cell: (s) => formatNumber(s.lines.length), sortValue: (s) => s.lines.length },
      { id: 'opening', header: 'Saldo inicial', width: 150, align: 'right', cell: (s) => <Amount cents={s.opening} currency={currency(s)} />, sortValue: (s) => s.opening },
      { id: 'closing', header: 'Saldo final', width: 150, align: 'right', cell: (s) => <Amount cents={s.closing} currency={currency(s)} />, sortValue: (s) => s.closing },
    ]
  }, [accounts])
  return (
    <Page fill>
      <PageHeader title="Datos" subtitle="Extractos bancarios del mes por cuenta, con su fichero original." filters={<SectionTabs />} />
      <DataTable
        aria-label="Extractos"
        rows={core.bankStatements}
        columns={columns}
        getRowId={(s) => `${s.account}/${s.month}`}
        onOpen={(s) => navigate(dataPath.statement(s.account, s.month))}
        globalKeys
      />
    </Page>
  )
}

export function StatementPage() {
  const { account = '', month = '' } = useParams()
  const api = useApi()
  const run = useRunItems()
  const openItem = useOpenItem()
  const statement = api.core.bankStatements.find((s) => s.account === account && s.month === month)
  const bank = api.core.bankAccounts.find((a) => a.id === account)
  const currency = bank?.currency ?? statement?.lines[0]?.currency ?? 'EUR'
  const iban = bank?.iban ?? bank?.clabe ?? null
  const [selected, setSelected] = useState<string | null>(null)
  const [raw, setRaw] = useState<{ key: string; details: Map<string, RawBankDetail> | null } | null>(null)
  const key = `${account}/${month}`

  useEffect(() => {
    let alive = true
    api.rawBankDetails(account, month).then(
      (list) => alive && setRaw({ key, details: new Map(list.map((d) => [d.bank_line, d])) }),
      () => alive && setRaw({ key, details: null }),
    )
    return () => {
      alive = false
    }
  }, [api, account, month, key])

  const columns = useMemo<Column<BankLine>[]>(
    () => [
      { id: 'line', header: 'Línea', width: 130, cell: (l) => <Mono>{l.bank_line}</Mono>, sortValue: (l) => l.bank_line },
      { id: 'booking', header: 'Fecha', width: 100, cell: (l) => formatDate(l.booking_date), sortValue: (l) => l.booking_date },
      { id: 'value', header: 'Valor', width: 100, cell: (l) => formatDate(l.value_date), sortValue: (l) => l.value_date },
      { id: 'amount', header: 'Importe', width: 150, align: 'right', cell: (l) => <Amount cents={l.amount} currency={l.currency || currency} signed colorize />, sortValue: (l) => l.amount },
      { id: 'text', header: 'Texto', width: 'minmax(240px, 2fr)', cell: (l) => <span className={styles.ellipsis}>{l.text}</span> },
      {
        id: 'items',
        header: 'Partidas',
        width: 'minmax(150px, 1fr)',
        cell: (l) => (
          <span className={styles.flags}>
            {bankLineItems(run?.itemsById ?? null, account, l.bank_line).map((it) => (
              <StatusBadge key={it.id} status={it.status} />
            ))}
          </span>
        ),
      },
    ],
    [run, account, currency],
  )

  if (!statement) return <NotFound what={`No hay extracto de ${account} para ${month}`} />
  const line = statement.lines.find((l) => l.bank_line === selected) ?? null
  const items = line ? bankLineItems(run?.itemsById ?? null, account, line.bank_line) : []
  const detail = line && raw?.key === key ? (raw.details?.get(line.bank_line) ?? null) : undefined

  return (
    <Page>
      <DetailHeader
        crumbs={[{ label: 'Datos', to: '/datos' }, { label: 'Extractos', to: '/datos/extractos' }, { label: `${account} · ${month}` }]}
        title={<Mono>{account}</Mono>}
        subtitle={`${bank?.bank ?? 'Cuenta bancaria'} · ${formatMonth(month)}`}
      />
      <Facts
        items={[
          { label: 'Sociedad', value: bank ? <Mono>{bank.company}</Mono> : '—' },
          { label: 'IBAN / CLABE', value: iban ? <Mono>{iban}</Mono> : '—' },
          { label: 'Cuenta contable', value: bank ? <TextLink to={dataPath.account(bank.gl_account)} mono>{bank.gl_account}</TextLink> : '—' },
          { label: 'Formato', value: FORMAT_LABEL[statement.format] },
          { label: 'Fichero', value: statement.rawPath ? <Mono>{fileName(statement.rawPath)}</Mono> : '—' },
          { label: 'Líneas', value: formatNumber(statement.lines.length) },
          { label: 'Saldo inicial', value: <Amount cents={statement.opening} currency={currency} /> },
          { label: 'Saldo final', value: <Amount cents={statement.closing} currency={currency} /> },
        ]}
      />
      <Section title="Líneas" count={statement.lines.length} description="Selecciona una línea para ver su registro original.">
        <DataTable
          aria-label={`Líneas de ${account}`}
          rows={statement.lines}
          columns={columns}
          getRowId={(l) => l.bank_line}
          selectedId={selected}
          onSelectedChange={setSelected}
          onOpen={(l) => setSelected(l.bank_line)}
          height={tableHeight(statement.lines.length, 480)}
          globalKeys
        />
      </Section>
      {line && (
        <Section
          title={<Mono>{line.bank_line}</Mono>}
          description={line.text}
          actions={items.map((it) => (
            <Button key={it.id} variant={it === items[0] ? 'primary' : 'secondary'} leadingIcon={<PanelRight />} onClick={() => openItem(it.id)}>
              {items.length > 1 ? `Abrir ${it.task === 'ar_cash' ? 'el cobro' : 'la conciliación'}` : 'Abrir la partida'}
            </Button>
          ))}
        >
          {detail === undefined ? (
            <Skeleton height={96} radius="var(--radius-lg)" />
          ) : detail === null ? (
            <p className={styles.muted}>El extracto original no trae más detalle para esta línea.</p>
          ) : (
            <>
              <pre className={styles.code}>{detail.raw.join('\n')}</pre>
              <Facts
                items={[
                  { label: 'Conceptos', value: detail.concepts.length ? detail.concepts.map((c, i) => <span key={i} className={styles.block}>{c}</span>) : '—' },
                  ...Object.entries(detail.references).map(([k, v]) => ({ label: k, value: <Mono>{v}</Mono> })),
                ]}
              />
            </>
          )}
        </Section>
      )}
    </Page>
  )
}
