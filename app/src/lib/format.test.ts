import {
  formatCompactMoney,
  formatDate,
  formatDateTime,
  formatDuration,
  formatMoney,
  formatMonth,
  formatNumber,
  formatPercent,
} from './format'

// Intl uses a no-break space (U+00A0) between number and currency/percent in es-ES.
const nb = (s: string) => s.replace(/ /g, ' ')

describe('formatMoney', () => {
  it('formats cents as es-ES EUR with grouping even for 4 digits', () => {
    expect(formatMoney(4202872)).toBe(nb('42.028,72 €'))
    expect(formatMoney(123450)).toBe(nb('1.234,50 €'))
    expect(formatMoney(0)).toBe(nb('0,00 €'))
  })

  it('uses the local currency of the company', () => {
    expect(formatMoney(123450, 'MXN')).toBe(nb('1.234,50 MXN'))
    expect(formatMoney(-99, 'USD')).toBe(nb('-0,99 US$'))
  })

  it('shows the sign of non-zero values when signed', () => {
    expect(formatMoney(123450, 'EUR', { signed: true })).toBe(nb('+1.234,50 €'))
    expect(formatMoney(-123450, 'EUR', { signed: true })).toBe(nb('-1.234,50 €'))
    expect(formatMoney(0, 'EUR', { signed: true })).toBe(nb('0,00 €'))
  })

  it('can drop decimals and the currency symbol', () => {
    expect(formatMoney(123456, 'EUR', { decimals: 0 })).toBe(nb('1.235 €'))
    expect(formatMoney(4202872, 'EUR', { currencyDisplay: 'none' })).toBe('42.028,72')
  })

  it('delegates to the compact form', () => {
    expect(formatMoney(123_456_789, 'EUR', { compact: true })).toBe('1,2 M€')
  })

  it('renders an em dash for missing amounts', () => {
    expect(formatMoney(null)).toBe('—')
    expect(formatMoney(undefined)).toBe('—')
  })
})

describe('formatCompactMoney', () => {
  it('uses M€ and k€ suffixes', () => {
    expect(formatCompactMoney(123_456_789)).toBe('1,2 M€')
    expect(formatCompactMoney(1_234_567)).toBe('12,3 k€')
    expect(formatCompactMoney(-4_500_000_000)).toBe('-45 M€')
  })

  it('keeps small amounts whole', () => {
    expect(formatCompactMoney(85_000)).toBe(nb('850 €'))
  })

  it('spells non-euro currencies after a space', () => {
    expect(formatCompactMoney(250_000_000, 'MXN')).toBe('2,5 M MXN')
  })

  it('supports the sign', () => {
    expect(formatCompactMoney(1_234_567, 'EUR', { signed: true })).toBe('+12,3 k€')
  })
})

describe('formatDate', () => {
  it('formats ISO dates without timezone drift', () => {
    expect(formatDate('2026-07-31')).toBe('31 jul 2026')
    expect(formatDate('2026-01-01')).toBe('1 ene 2026')
  })

  it('accepts full timestamps', () => {
    expect(formatDate('2026-07-31T23:30:00Z')).toBe('31 jul 2026')
  })

  it('returns an em dash for empty or invalid input', () => {
    expect(formatDate(null)).toBe('—')
    expect(formatDate('not a date')).toBe('—')
  })
})

describe('formatMonth', () => {
  it('formats a YYYY-MM month', () => {
    expect(formatMonth('2026-07')).toBe('jul 2026')
  })
})

describe('formatDateTime', () => {
  it('includes the time in 24h format', () => {
    expect(formatDateTime('2026-10-03T10:03:12Z', { timeZone: 'UTC' })).toBe('3 oct 2026, 10:03')
  })

  it('returns an em dash for empty input', () => {
    expect(formatDateTime(null)).toBe('—')
  })
})

describe('formatPercent', () => {
  it('formats ratios with one decimal by default', () => {
    expect(formatPercent(0.934)).toBe(nb('93,4 %'))
    expect(formatPercent(1)).toBe(nb('100 %'))
  })

  it('accepts a fixed number of decimals', () => {
    expect(formatPercent(1, { decimals: 2 })).toBe(nb('100,00 %'))
  })

  it('returns an em dash for null', () => {
    expect(formatPercent(null)).toBe('—')
  })
})

describe('formatNumber', () => {
  it('groups thousands with dots', () => {
    expect(formatNumber(36743)).toBe('36.743')
    expect(formatNumber(1234)).toBe('1.234')
    expect(formatNumber(0.5, { decimals: 2 })).toBe('0,50')
  })
})

describe('formatDuration', () => {
  it('picks the unit by magnitude', () => {
    expect(formatDuration(3)).toBe('3 ms')
    expect(formatDuration(4200)).toBe('4,2 s')
    expect(formatDuration(1_300_000)).toBe('21 min 40 s')
    expect(formatDuration(3_900_000)).toBe('1 h 05 min')
  })

  it('returns an em dash for null', () => {
    expect(formatDuration(null)).toBe('—')
  })
})
