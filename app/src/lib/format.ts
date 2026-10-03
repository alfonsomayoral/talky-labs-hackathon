// Spanish (es-ES) formatting for amounts, dates and durations.
// Amounts arrive as integer cents in the company's local currency (EUR, MXN in 3100).
// es-ES skips grouping for 4-digit numbers by default; accounting needs `1.234,56`, so grouping is forced.

const LOCALE = 'es-ES'
const EMPTY = '—'

const numberFormats = new Map<string, Intl.NumberFormat>()
function nf(options: Intl.NumberFormatOptions): Intl.NumberFormat {
  const key = JSON.stringify(options)
  let f = numberFormats.get(key)
  if (!f) {
    f = new Intl.NumberFormat(LOCALE, { useGrouping: 'always', ...options })
    numberFormats.set(key, f)
  }
  return f
}

export interface MoneyOptions {
  /** Prefix `+` on positive values. */
  signed?: boolean
  /** Fraction digits; defaults to 2. */
  decimals?: 0 | 2
  /** `1,2 M€` style (see formatCompactMoney). */
  compact?: boolean
  /** `none` prints the bare number (e.g. in a column whose header carries the currency). */
  currencyDisplay?: 'symbol' | 'none'
}

export function formatMoney(cents: number | null | undefined, currency = 'EUR', opts: MoneyOptions = {}): string {
  if (cents == null || !Number.isFinite(cents)) return EMPTY
  if (opts.compact) return formatCompactMoney(cents, currency, { signed: opts.signed })
  const decimals = opts.decimals ?? 2
  const base: Intl.NumberFormatOptions = {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
    signDisplay: opts.signed ? 'exceptZero' : 'auto',
  }
  const options: Intl.NumberFormatOptions =
    opts.currencyDisplay === 'none' ? base : { ...base, style: 'currency', currency }
  return nf(options).format(cents / 100)
}

const COMPACT_SYMBOL: Record<string, string> = { EUR: '€', USD: 'US$' }

/** `1,2 M€`, `12,3 k€`, `850 €`; non-euro currencies as `2,5 M MXN`. */
export function formatCompactMoney(cents: number | null | undefined, currency = 'EUR', opts: { signed?: boolean } = {}): string {
  if (cents == null || !Number.isFinite(cents)) return EMPTY
  const units = cents / 100
  const abs = Math.abs(units)
  if (abs < 1000) return formatMoney(cents, currency, { decimals: 0, signed: opts.signed })
  const [divisor, suffix] = abs >= 1e6 ? [1e6, 'M'] : [1e3, 'k']
  const value = nf({ maximumFractionDigits: 1, signDisplay: opts.signed ? 'exceptZero' : 'auto' }).format(units / divisor)
  const symbol = COMPACT_SYMBOL[currency]
  return symbol === '€' ? `${value} ${suffix}€` : `${value} ${suffix} ${symbol ?? currency}`
}

const dateFormats = new Map<string, Intl.DateTimeFormat>()
function df(options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = JSON.stringify(options)
  let f = dateFormats.get(key)
  if (!f) {
    f = new Intl.DateTimeFormat(LOCALE, options)
    dateFormats.set(key, f)
  }
  return f
}

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/

function toDate(value: string | Date): Date | null {
  const d = value instanceof Date ? value : new Date(DATE_ONLY.test(value) ? `${value}T00:00:00Z` : value)
  return Number.isNaN(d.getTime()) ? null : d
}

/** `2026-07-31` → `31 jul 2026`. Calendar dates are read as UTC so they never shift a day. */
export function formatDate(value: string | Date | null | undefined): string {
  if (value == null || value === '') return EMPTY
  const d = toDate(value)
  if (!d) return EMPTY
  const timeZone = typeof value === 'string' && (DATE_ONLY.test(value) || value.endsWith('Z')) ? 'UTC' : undefined
  return df({ day: 'numeric', month: 'short', year: 'numeric', timeZone }).format(d)
}

/** `2026-07` → `jul 2026`. */
export function formatMonth(month: string | null | undefined): string {
  if (!month) return EMPTY
  const d = toDate(`${month.slice(0, 7)}-01`)
  return d ? df({ month: 'short', year: 'numeric', timeZone: 'UTC' }).format(d) : EMPTY
}

/** ISO timestamp → `3 oct 2026, 12:03` in the viewer's time zone (or the given one). */
export function formatDateTime(value: string | Date | null | undefined, opts: { timeZone?: string } = {}): string {
  if (value == null || value === '') return EMPTY
  const d = toDate(value)
  if (!d) return EMPTY
  return df({
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
    timeZone: opts.timeZone,
  }).format(d)
}

/** Ratio 0..1 → `93,4 %`. */
export function formatPercent(ratio: number | null | undefined, opts: { decimals?: number; signed?: boolean } = {}): string {
  if (ratio == null || !Number.isFinite(ratio)) return EMPTY
  const decimals = opts.decimals
  return nf({
    style: 'percent',
    minimumFractionDigits: decimals ?? 0,
    maximumFractionDigits: decimals ?? 1,
    signDisplay: opts.signed ? 'exceptZero' : 'auto',
  }).format(ratio)
}

export function formatNumber(value: number | null | undefined, opts: { decimals?: number } = {}): string {
  if (value == null || !Number.isFinite(value)) return EMPTY
  const decimals = opts.decimals
  return nf({ minimumFractionDigits: decimals ?? 0, maximumFractionDigits: decimals ?? 2 }).format(value)
}

/** `3 ms`, `4,2 s`, `21 min 40 s`, `1 h 05 min`. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return EMPTY
  if (ms < 1000) return `${Math.round(ms)} ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${nf({ maximumFractionDigits: 1 }).format(seconds)} s`
  const total = Math.round(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  if (h > 0) return `${h} h ${String(m).padStart(2, '0')} min`
  return s > 0 ? `${m} min ${s} s` : `${m} min`
}
