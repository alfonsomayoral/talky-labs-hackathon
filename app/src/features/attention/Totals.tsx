import { Fragment } from 'react'
import { Amount } from '@/components'
import type { CurrencyTotal } from './attentionModel'

/** «11,3 M€ + 7,1 M MXN»: one compact amount per currency. */
export function Totals({ totals, compact }: { totals: CurrencyTotal[]; compact?: boolean }) {
  return (
    <span>
      {totals.map((t, i) => (
        <Fragment key={t.currency}>
          {i > 0 && ' + '}
          <Amount cents={t.cents} currency={t.currency} compact={compact} />
        </Fragment>
      ))}
    </span>
  )
}
