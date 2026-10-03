// EUR totals over items of several companies. Uses the engine's `makeToEur` (company currency at the
// month-end SYN-BCE rate); a document in a third currency (an AP invoice in USD booked in 1000) is
// converted by its own currency with the engine's `rateAt`.

import type { DatasetCore, WorkItem } from '@/domain/types'
import { makeToEur, rateAt, type ToEur } from '@/engine'

interface FxCache {
  toEur: ToEur
  currencyOf: Map<string, string>
  rates: Map<string, number | null>
  date: string
}

const cache = new WeakMap<DatasetCore, FxCache>()

function fx(core: DatasetCore): FxCache {
  let c = cache.get(core)
  if (!c) {
    const [y, m] = core.tasks.close.month.split('-').map(Number)
    c = {
      toEur: makeToEur(core),
      currencyOf: new Map(core.companies.map((x) => [x.code, x.currency])),
      rates: new Map(),
      date: new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10),
    }
    cache.set(core, c)
  }
  return c
}

/** `cents` of an item (in `item.currency`) → EUR cents. */
export function itemEurCents(item: Pick<WorkItem, 'company' | 'currency'>, cents: number, core: DatasetCore): number {
  const c = fx(core)
  const own = item.company ? c.currencyOf.get(item.company) : undefined
  if (!item.currency || item.currency === own) return c.toEur(item.company, cents)
  if (item.currency === 'EUR') return cents
  if (!c.rates.has(item.currency)) c.rates.set(item.currency, rateAt(core, item.currency, c.date))
  const rate = c.rates.get(item.currency)
  return rate ? Math.round(cents / rate) : cents
}
