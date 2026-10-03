// Bank and book face to face: one block per match (its statement lines left, its 572 lines right, joined by
// connectors) or per unmatched line, in date order.
import clsx from 'clsx'
import { Amount, Badge, Mono } from '@/components'
import { BANK_CATEGORY_CATALOG } from '@/domain/catalog/policy'
import { formatDate } from '@/lib/format'
import type { RecBlock, RecLine } from './model'
import styles from './Bank.module.css'

const ROW = 34
const GUTTER = 88

interface Props {
  blocks: RecBlock[]
  currency: string
  selectedId: string | null
  onSelect: (line: RecLine) => void
}

const categoryLabel = (c: string) => BANK_CATEGORY_CATALOG[c as keyof typeof BANK_CATEGORY_CATALOG]?.label ?? c

export function RecFaceView({ blocks, currency, selectedId, onSelect }: Props) {
  return (
    <div className={styles.face} role="table" aria-label="Extracto frente a libro">
      <div className={styles.faceHead} role="row">
        <span role="columnheader">Extracto del banco</span>
        <span role="columnheader" className={styles.faceGutterHead}>
          Casación
        </span>
        <span role="columnheader">Libro (cuenta 572)</span>
      </div>
      {blocks.map((b) => {
        const bank = b.kind === 'match' ? b.group.bank : b.kind === 'bank' ? [b.line] : []
        const book = b.kind === 'match' ? b.group.book : b.kind === 'book' ? [b.line] : []
        const rows = Math.max(bank.length, book.length, 1)
        const key = b.kind === 'match' ? `m${b.group.index}` : `${b.kind}:${b.line.id}`
        return (
          <div key={key} className={clsx(styles.block, b.kind !== 'match' && styles.blockLone)} role="row">
            <div className={styles.side}>
              {bank.map((l) => (
                <LineRow key={l.id} line={l} currency={currency} selected={selectedId === l.id} onSelect={onSelect} />
              ))}
            </div>
            <div className={styles.gutter}>
              {b.kind === 'match' ? (
                <Connectors bank={bank.length} book={book.length} rows={rows} diff={b.group.diff !== 0} shape={b.group.shape} />
              ) : (
                <span className={styles.loneTag}>
                  <Badge tone={BANK_CATEGORY_CATALOG[b.line.category as keyof typeof BANK_CATEGORY_CATALOG]?.adjustment ? 'warn' : 'neutral'} variant="outline">
                    {b.kind === 'bank' ? 'Solo banco' : 'Solo libro'}
                  </Badge>
                </span>
              )}
            </div>
            <div className={styles.side}>
              {book.map((l) => (
                <LineRow key={l.id} line={l} currency={currency} selected={selectedId === l.id} onSelect={onSelect} />
              ))}
            </div>
            {(b.kind !== 'match' || b.group.category) && (
              <div className={styles.blockNote}>
                {categoryLabel(b.kind === 'match' ? b.group.category! : b.line.category ?? '')}
                {b.kind === 'match' && b.group.diff !== 0 && (
                  <>
                    {' · diferencia '}
                    <Amount cents={b.group.diff} currency={currency} signed />
                  </>
                )}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

function LineRow({ line, currency, selected, onSelect }: { line: RecLine; currency: string; selected: boolean; onSelect: (l: RecLine) => void }) {
  return (
    <button type="button" className={clsx(styles.line, selected && styles.lineSelected, !line.known && styles.lineUnknown)} style={{ height: ROW }} onClick={() => onSelect(line)}>
      <span className={styles.lineDate}>{line.date ? formatDate(line.date) : '—'}</span>
      <Mono muted>{line.id}</Mono>
      <span className={styles.lineText} title={line.text}>
        {line.text || (line.known ? '' : 'Fuera del extracto o del mes')}
      </span>
      <span className={styles.lineAmount}>
        <Amount cents={line.amount} currency={currency} colorize />
      </span>
    </button>
  )
}

function Connectors({ bank, book, rows, diff, shape }: { bank: number; book: number; rows: number; diff: boolean; shape: string }) {
  const h = rows * ROW
  const y = (i: number) => i * ROW + ROW / 2
  const paths: string[] = []
  for (let i = 0; i < bank; i++)
    for (let j = 0; j < book; j++) paths.push(`M0,${y(i)} C${GUTTER / 2},${y(i)} ${GUTTER / 2},${y(j)} ${GUTTER},${y(j)}`)
  return (
    <svg className={clsx(styles.connectors, diff && styles.connectorsDiff)} width={GUTTER} height={h} viewBox={`0 0 ${GUTTER} ${h}`} aria-label={`Casación ${shape}`}>
      {paths.map((d, k) => (
        <path key={k} d={d} />
      ))}
      <text x={GUTTER / 2} y={10} textAnchor="middle" className={styles.shape}>
        {shape}
      </text>
    </svg>
  )
}
