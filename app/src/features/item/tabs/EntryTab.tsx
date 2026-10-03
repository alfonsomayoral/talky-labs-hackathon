import { BookX } from 'lucide-react'
import { outcomeEntry } from '@/domain/catalog/policy'
import { EmptyState } from '@/components'
import { JournalEntryView, type ItemContext } from '../kit'
import styles from './tabs.module.css'

function noEntryReason(ctx: ItemContext): string {
  const { item } = ctx
  const label = outcomeEntry(item.task, item.outcome)?.label ?? item.outcome
  switch (item.task) {
    case 'ap':
      return item.outcome === 'POST' || item.outcome === 'POST_PAYMENT_BLOCK' ? 'La entrega no trae journal_entry para esta factura.' : `No se contabiliza: ${label.toLowerCase()}.`
    case 'ar_billing':
      return item.outcome === 'SKIP_PENDING_APPROVAL' ? 'No se factura: la obra pendiente de certificar se registra en Cierre.' : 'La entrega no trae journal_entry para esta partida.'
    case 'ar_cash':
      return 'La entrega no trae asiento de ajuste para este abono.'
    case 'bank_rec':
      return item.outcome === 'MATCH' ? 'Casada sin diferencia: no necesita asiento.' : `${label}: sin asiento de ajuste en esta partida.`
    case 'ic':
      return item.status === 'OPEN' ? 'Sin ajuste aquí: se corrige en la conciliación bancaria.' : 'La entrega no trae ajuste para esta diferencia.'
    case 'close':
      return 'La entrega no trae journal_entry para esta partida de cierre.'
  }
}

/** The entries the item adds to the ledger (what the trial balance sees). */
export function EntryTab({ ctx }: { ctx: ItemContext }) {
  const { entries, item } = ctx
  if (!entries.length) return <EmptyState size="sm" icon={<BookX />} title="Sin asiento" description={noEntryReason(ctx)} />
  const adjustments = item.task === 'bank_rec' && Array.isArray(ctx.rows[0]?.adjustments) ? (ctx.rows[0].adjustments as unknown[]).length : 0
  return (
    <div className={styles.entries}>
      {entries.map((e, i) => (
        <JournalEntryView key={i} entry={e} title={entries.length > 1 ? `Asiento ${i + 1} de ${entries.length}` : 'Asiento entregado'} />
      ))}
      {adjustments > entries.length && (
        <p className={styles.note}>
          La cuenta lleva {adjustments} ajustes; esta partida tiene {entries.length === 1 ? 'el suyo' : `${entries.length}`}. El resto está en sus partidas.
        </p>
      )}
    </div>
  )
}
