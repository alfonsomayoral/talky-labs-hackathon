// Group-level totals in EUR. Deliverables and the scorer keep local-currency cents
// (MXN in 3100); summing those across companies mixes currencies, so the views
// convert to EUR at the SYN-BCE rate of the month end (last published rate).

import type { Cents, DatasetCore } from '@/domain/types'

export type ToEur = (company: string | null | undefined, cents: Cents) => Cents

const monthEnd = (month: string) => {
  const [y, m] = month.split('-').map(Number)
  return new Date(Date.UTC(y, m, 0)).toISOString().slice(0, 10)
}

/** EUR per unit of `currency` is 1 / rate (rates are quoted as currency per EUR). */
export function rateAt(core: DatasetCore, currency: string, date: string): number | null {
  let best: { date: string; rate: number } | null = null
  for (const r of core.fxRates) {
    if (r.base !== 'EUR' || r.currency !== currency || r.date > date) continue
    if (!best || r.date > best.date) best = { date: r.date, rate: r.rate }
  }
  return best?.rate ?? null
}

export function makeToEur(core: DatasetCore): ToEur {
  const date = monthEnd(core.tasks.close.month)
  const currencyOf = new Map(core.companies.map((c) => [c.code, c.currency]))
  const rates = new Map<string, number | null>()
  return (company, cents) => {
    const currency = (company && currencyOf.get(company)) || 'EUR'
    if (currency === 'EUR') return cents
    if (!rates.has(currency)) rates.set(currency, rateAt(core, currency, date))
    const rate = rates.get(currency)
    return rate ? Math.round(cents / rate) : cents
  }
}
