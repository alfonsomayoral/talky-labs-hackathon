import clsx from 'clsx'
import { CircleCheck } from 'lucide-react'
import type { FieldDiff, ItemScore } from '@/domain/types'
import { accountLabel } from '@/domain/catalog/policy'
import { useDatasetStore } from '@/data/stores'
import { Amount, Badge, EmptyState, Mono } from '@/components'
import { formatPercent } from '@/lib/format'
import styles from './GoldenDiff.module.css'

export interface GoldenDiffProps {
  score: ItemScore
  /** Currency of amounts inside line diffs. */
  currency?: string
  title?: string
  className?: string
}

const PATH_LABELS: Record<string, string> = {
  item: 'Partida',
  decision: 'Decisión',
  reasons: 'Motivos',
  duplicate_of: 'Duplicado de',
  'lines.coding': 'Imputación de línea',
  'lines.po': 'Pedido y posición',
  'journal_entry.lines': 'Asiento',
  payee: 'Beneficiario',
  payment_block: 'Bloqueo de pago',
  expected: 'Decisión',
  customer: 'Cliente',
  applications: 'Aplicaciones',
  residuals: 'Diferencias',
  adjustment: 'Asiento de ajuste',
  adjustments: 'Asientos de ajuste',
  matches: 'Casaciones',
  unmatched_bank: 'Sin casar en el extracto',
  unmatched_book: 'Sin casar en libros',
  'unmatched_bank.category': 'Categoría (extracto)',
  'unmatched_book.category': 'Categoría (libros)',
  amount: 'Importe',
}

export function diffLabel(path: string): string {
  if (PATH_LABELS[path]) return PATH_LABELS[path]
  if (path.startsWith('header.')) return `Cabecera · ${path.slice(7)}`
  if (path.startsWith('invoice.')) return `Factura · ${path.slice(8)}`
  return path
}

type Line = { account: string; amount: number; partner?: unknown; cost_center?: unknown; wbs?: unknown }

const isLineList = (v: unknown): v is Line[] =>
  Array.isArray(v) && v.every((x) => x && typeof x === 'object' && 'account' in x && 'amount' in (x as object))

const isObjectList = (v: unknown): v is Record<string, unknown>[] => Array.isArray(v) && v.length > 0 && v.every((x) => x && typeof x === 'object' && !Array.isArray(x))

/** Golden comparison of an item: «Coincide con la referencia», or each field that differs (lines as two aligned tables). */
export function GoldenDiff({ score, currency = 'EUR', title, className }: GoldenDiffProps) {
  const pct = score.score !== null ? formatPercent(score.score, { decimals: 0 }) : null
  if (score.exact && !score.diffs.length) {
    return (
      <div className={clsx(styles.exact, className)}>
        <EmptyState size="sm" icon={<CircleCheck />} title="Coincide con la referencia" description={title ? `${title}: sin diferencias${pct ? ` · ${pct}` : ''}.` : `Sin diferencias con golden${pct ? ` · ${pct}` : ''}.`} />
      </div>
    )
  }
  return (
    <div className={clsx(styles.diff, className)}>
      <header className={styles.header}>
        <span className={styles.title}>{title ?? 'Diferencias con la referencia'}</span>
        {pct && <Badge tone={score.score === 1 ? 'ok' : (score.score ?? 0) >= 0.5 ? 'warn' : 'danger'}>{pct} del crédito</Badge>}
      </header>
      <ol className={styles.list}>
        {score.diffs.map((d, i) => (
          <li key={`${d.path}-${i}`} className={styles.item}>
            <Mono className={styles.path}>{diffLabel(d.path)}</Mono>
            <DiffBody diff={d} currency={currency} />
          </li>
        ))}
      </ol>
    </div>
  )
}

function DiffBody({ diff, currency }: { diff: FieldDiff; currency: string }) {
  const { expected, actual } = diff
  const money = diff.path === 'amount' || diff.path.endsWith('.amount')
  if ((isLineList(expected) || expected === null) && (isLineList(actual) || actual === null) && (isLineList(expected) || isLineList(actual))) {
    return <LineTables expected={(expected as Line[] | null) ?? []} actual={(actual as Line[] | null) ?? []} currency={currency} />
  }
  if (isObjectList(expected) || isObjectList(actual)) {
    return (
      <div className={styles.columns}>
        <ObjectList title="Referencia" rows={Array.isArray(expected) ? (expected as Record<string, unknown>[]) : []} currency={currency} />
        <ObjectList title="Entrega" rows={Array.isArray(actual) ? (actual as Record<string, unknown>[]) : []} currency={currency} />
      </div>
    )
  }
  return (
    <div className={styles.columns}>
      <div className={styles.side}>
        <span className={styles.sideTitle}>Referencia</span>
        <Value value={expected} money={money} currency={currency} />
      </div>
      <div className={clsx(styles.side, styles.actual)}>
        <span className={styles.sideTitle}>Entrega</span>
        <Value value={actual} money={money} currency={currency} />
      </div>
    </div>
  )
}

function Value({ value, money, currency }: { value: unknown; money: boolean; currency: string }) {
  if (value === null || value === undefined) return <span className={styles.none}>—</span>
  if (money && typeof value === 'number') return <Amount cents={value} currency={currency} />
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return <Mono>{String(value)}</Mono>
  if (Array.isArray(value) && value.every((v) => typeof v !== 'object')) return <Mono>{value.length ? value.join(', ') : '[]'}</Mono>
  return <code className={styles.code}>{JSON.stringify(value)}</code>
}

function ObjectList({ title, rows, currency }: { title: string; rows: Record<string, unknown>[]; currency: string }) {
  return (
    <div className={styles.side}>
      <span className={styles.sideTitle}>{title}</span>
      {rows.length === 0 ? (
        <span className={styles.none}>—</span>
      ) : (
        <ul className={styles.objects}>
          {rows.map((r, i) => (
            <li key={i}>
              {Object.entries(r).map(([k, v]) =>
                k === 'amount' && typeof v === 'number' ? (
                  <Amount key={k} cents={v} currency={currency} />
                ) : (
                  <Mono key={k}>{v === null || v === undefined ? '—' : String(v)}</Mono>
                ),
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function LineTables({ expected, actual, currency }: { expected: Line[]; actual: Line[]; currency: string }) {
  const chart = useDatasetStore((s) => s.api?.core.chartOfAccounts ?? null)
  const rows = Math.max(expected.length, actual.length)
  const cell = (l: Line | undefined) =>
    l ? (
      <>
        <span className={styles.lineAccount}>
          <Mono>{l.account}</Mono>
          <span className={styles.lineLabel}>{accountLabel(l.account, chart)}</span>
        </span>
        <span className={styles.lineObjects}>{[l.partner, l.cost_center, l.wbs].filter((x) => x !== null && x !== undefined && x !== '').map(String).join(' · ')}</span>
        <Amount cents={l.amount} currency={currency} signed className={styles.lineAmount} />
      </>
    ) : null
  return (
    <div className={styles.lineTables}>
      <div className={styles.lineHead}>Faltan (referencia)</div>
      <div className={styles.lineHead}>Sobran (entrega)</div>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className={styles.linePair}>
          <div className={clsx(styles.line, expected[i] && styles.missing)}>{cell(expected[i])}</div>
          <div className={clsx(styles.line, actual[i] && styles.extra)}>{cell(actual[i])}</div>
        </div>
      ))}
      <p className={styles.legend}>Importe con signo: debe positivo, haber negativo.</p>
    </div>
  )
}
