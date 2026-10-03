import clsx from 'clsx'
import { Landmark } from 'lucide-react'
import type { DatasetApi, RawBankDetail } from '@/domain/types'
import { useDatasetStore } from '@/data/stores'
import { Amount, EmptyState, KeyValue, Mono, Skeleton } from '@/components'
import { formatDate } from '@/lib/format'
import { findStatementLine } from './evidence'
import { useAsync } from './useAsync'
import styles from './RawBankRecord.module.css'

export interface RawBankRecordProps {
  bankLine: string
  className?: string
}

const cache = new WeakMap<DatasetApi, Map<string, Promise<RawBankDetail[]>>>()

function rawDetails(api: DatasetApi, account: string, month: string): Promise<RawBankDetail[]> {
  let byKey = cache.get(api)
  if (!byKey) cache.set(api, (byKey = new Map()))
  const key = `${account}/${month}`
  let p = byKey.get(key)
  if (!p) {
    p = api.rawBankDetails(account, month)
    byKey.set(key, p)
    p.catch(() => byKey?.delete(key))
  }
  return p
}

const N43_RECORDS: Record<string, string> = { '11': 'Cabecera de cuenta', '22': 'Movimiento', '23': 'Concepto', '24': 'Equivalencia', '33': 'Final de cuenta' }

/** A statement line as the bank sent it: the parsed line plus the raw N43 records / CAMT entry / CSV row. */
export function RawBankRecord({ bankLine, className }: RawBankRecordProps) {
  const api = useDatasetStore((s) => s.api)
  const ref = api ? findStatementLine(api.core, bankLine) : null
  const statement = ref && api ? api.core.bankStatements.find((s) => s.account === ref.account && s.month === ref.month) : undefined
  const state = useAsync(async () => {
    if (!api || !ref) return null
    const details = await rawDetails(api, ref.account, ref.month)
    return details.find((d) => d.bank_line === bankLine) ?? null
  }, [api, bankLine, ref?.account, ref?.month])

  if (!ref) return <EmptyState size="sm" icon={<Landmark />} title={`La línea ${bankLine} no está en los extractos cargados`} />
  const { line } = ref
  return (
    <div className={clsx(styles.record, className)}>
      <KeyValue
        columns={2}
        labelWidth={88}
        items={[
          { label: 'Cuenta', value: ref.account, mono: true },
          { label: 'Formato', value: statement ? statement.format.toUpperCase() : '—' },
          { label: 'Fecha', value: formatDate(line.booking_date) },
          { label: 'Valor', value: formatDate(line.value_date) },
          { label: 'Importe', value: <Amount cents={line.amount} currency={line.currency} signed colorize /> },
          { label: 'Moneda', value: line.currency },
        ]}
      />
      <p className={styles.text}>{line.text}</p>
      {state.status === 'loading' && <Skeleton lines={2} />}
      {state.status === 'ready' && state.data && <RawDetail detail={state.data} />}
      {state.status === 'ready' && !state.data && <p className={styles.muted}>Sin registro bruto para esta línea.</p>}
      {state.status === 'error' && <p className={styles.muted}>No se pudo leer el extracto: {state.error}</p>}
    </div>
  )
}

function RawDetail({ detail }: { detail: RawBankDetail }) {
  const refs = Object.entries(detail.references ?? {})
  return (
    <div className={styles.raw}>
      {detail.raw.length > 0 && (
        <div className={styles.records}>
          {detail.raw.map((r, i) => {
            const type = r.slice(0, 2)
            return (
              <div key={i} className={styles.recordLine}>
                <span className={styles.recordType} title={N43_RECORDS[type] ?? 'Registro'}>
                  {N43_RECORDS[type] ? type : '·'}
                </span>
                <code className={styles.code}>{r}</code>
              </div>
            )
          })}
        </div>
      )}
      {detail.concepts.length > 0 && (
        <div className={styles.concepts}>
          {detail.concepts.map((c, i) => (
            <span key={i} className={styles.concept}>
              {c}
            </span>
          ))}
        </div>
      )}
      {refs.length > 0 && <KeyValue labelWidth={120} items={refs.map(([k, v]) => ({ label: k, value: <Mono>{v}</Mono> }))} />}
    </div>
  )
}
