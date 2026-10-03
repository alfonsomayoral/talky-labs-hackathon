import { useMemo, type ReactNode } from 'react'
import clsx from 'clsx'
import { Check, X } from 'lucide-react'
import type { ChartAccount, JeLine, JournalEntryOut } from '@/domain/types'
import { accountLabel } from '@/domain/catalog/policy'
import { useDatasetStore } from '@/data/stores'
import { Amount, Badge, Mono } from '@/components'
import { formatDate } from '@/lib/format'
import { journalTotals } from './journal'
import styles from './JournalEntryView.module.css'

export interface JournalEntryViewProps {
  /** A delivered or recorded entry (`{company, lines, id?, posting_date?…}`)… */
  entry?: JournalEntryOut | null
  /** …or bare lines (ar_cash / ic / bank adjustments), each with its own `company`. */
  lines?: readonly JeLine[]
  /** Default company of lines without one. */
  company?: string | null
  /** Currency of the amounts; defaults to the entry's or the company's. */
  currency?: string
  /** Chart of accounts for labels; defaults to the active dataset's. */
  chart?: readonly ChartAccount[]
  title?: ReactNode
  /** Line numbers to highlight (1-based `line` field or position). */
  highlight?: number[]
  className?: string
}

const str = (x: unknown): string | null => (typeof x === 'string' && x ? x : null)

/** Lines table (account + label, partner, cost object, debit, credit) with totals and a balanced ✓/✗ badge. */
export function JournalEntryView({ entry, lines: bare, company, currency, chart, title, highlight, className }: JournalEntryViewProps) {
  const core = useDatasetStore((s) => s.api?.core ?? null)
  const lines = useMemo(() => (entry?.lines ?? bare ?? []) as JeLine[], [entry, bare])
  const defaultCompany = company ?? entry?.company ?? null
  const totals = useMemo(() => journalTotals(lines, defaultCompany), [lines, defaultCompany])
  const accounts = chart ?? core?.chartOfAccounts ?? null
  const companyCurrency = (code: string | null) => (code ? core?.companies?.find((c) => c.code === code)?.currency : undefined)
  const cur = currency ?? str(entry?.currency) ?? companyCurrency(defaultCompany) ?? 'EUR'
  const multiCompany = totals.companies.length > 1
  const meta = [
    str(entry?.id) && <Mono key="id">{String(entry?.id)}</Mono>,
    str(entry?.doc_type) && <span key="dt">{String(entry?.doc_type)}</span>,
    str(entry?.posting_date) && <span key="pd">{formatDate(String(entry?.posting_date))}</span>,
    str(entry?.reference) && <span key="ref">Ref. {String(entry?.reference)}</span>,
    str(entry?.source) && <span key="src">{String(entry?.source)}</span>,
  ].filter(Boolean)

  return (
    <section className={clsx(styles.entry, className)}>
      {(title || meta.length > 0 || defaultCompany) && (
        <header className={styles.header}>
          <div className={styles.heading}>
            {title && <h4 className={styles.title}>{title}</h4>}
            {meta.length > 0 && <div className={styles.meta}>{meta}</div>}
            {str(entry?.header_text) && <p className={styles.text}>{String(entry?.header_text)}</p>}
          </div>
          {!multiCompany && defaultCompany && <Badge variant="outline">Sociedad {defaultCompany}</Badge>}
        </header>
      )}
      <div className={styles.scroll}>
        <table className={styles.table}>
          <thead>
            <tr>
              {multiCompany && <th className={styles.company}>Soc.</th>}
              <th className={styles.accountCol}>Cuenta</th>
              <th>Socio · objeto</th>
              <th className={styles.num}>Debe</th>
              <th className={styles.num}>Haber</th>
            </tr>
          </thead>
          <tbody>
            {lines.map((l, i) => {
              const n = typeof l.line === 'number' ? l.line : i + 1
              const lineCurrency = multiCompany ? (companyCurrency(str(l.company) ?? defaultCompany) ?? cur) : cur
              const cost = [str(l.cost_center), str(l.wbs)].filter(Boolean).join(' · ')
              const label = accountLabel(String(l.account), accounts)
              return (
                <tr key={i} className={clsx(highlight?.includes(n) && styles.highlight)}>
                  {multiCompany && (
                    <td className={styles.company}>
                      <Mono>{String(l.company ?? defaultCompany ?? '—')}</Mono>
                    </td>
                  )}
                  <td className={styles.shrink}>
                    <span className={styles.account} title={`${String(l.account)} ${label}`}>
                      <Mono>{String(l.account)}</Mono>
                      <span className={styles.accountLabel}>{label}</span>
                    </span>
                    {str(l.text) && (
                      <span className={styles.lineText} title={String(l.text)}>
                        {String(l.text)}
                      </span>
                    )}
                  </td>
                  <td className={styles.shrink}>
                    {str(l.partner) || cost || str(l.assignment) ? (
                      <span className={styles.objects}>
                        {str(l.partner) && <Mono>{String(l.partner)}</Mono>}
                        {cost && <Mono muted>{cost}</Mono>}
                        {str(l.assignment) && <span className={styles.assignment}>{String(l.assignment)}</span>}
                      </span>
                    ) : (
                      <span className={styles.none}>—</span>
                    )}
                  </td>
                  <td className={styles.num}>{l.debit ? <Amount cents={Number(l.debit)} currency={lineCurrency} hideCurrency /> : null}</td>
                  <td className={styles.num}>{l.credit ? <Amount cents={Number(l.credit)} currency={lineCurrency} hideCurrency /> : null}</td>
                </tr>
              )
            })}
          </tbody>
          <tfoot>
            <tr>
              <td colSpan={multiCompany ? 3 : 2}>
                {totals.balanced ? (
                  <Badge tone="ok" icon={<Check aria-hidden />}>
                    Cuadrado
                  </Badge>
                ) : (
                  <Badge tone="danger" icon={<X aria-hidden />}>
                    Descuadre{' '}
                    {[...totals.imbalance].map(([c, v]) => (
                      <span key={c}>
                        {multiCompany && c ? `${c}: ` : ''}
                        <Amount cents={v} currency={companyCurrency(c) ?? cur} signed />
                      </span>
                    ))}
                  </Badge>
                )}
                <span className={styles.lineCount}>
                  {lines.length} {lines.length === 1 ? 'línea' : 'líneas'} · {cur}
                </span>
              </td>
              <td className={styles.num}>
                <Amount cents={totals.debit} currency={cur} hideCurrency />
              </td>
              <td className={styles.num}>
                <Amount cents={totals.credit} currency={cur} hideCurrency />
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
    </section>
  )
}
