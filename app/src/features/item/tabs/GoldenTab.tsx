import { GoldenDiff, type ItemContext } from '../kit'
import styles from './tabs.module.css'

/** Comparison with golden: the item, and for bank items the account (adjustments are scored per account). */
export function GoldenTab({ ctx }: { ctx: ItemContext }) {
  const cur = ctx.item.currency ?? 'EUR'
  const account = ctx.item.task === 'bank_rec' ? ctx.item.key.split('/')[0] : null
  return (
    <div className={styles.stack}>
      {ctx.score && <GoldenDiff score={ctx.score} currency={cur} />}
      {ctx.accountScore && <GoldenDiff score={ctx.accountScore} currency={cur} title={`Cuenta ${account} (ajustes)`} />}
    </div>
  )
}
