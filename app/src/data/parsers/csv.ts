// Minimal CSV (RFC 4180 quotes) plus the Mexican bank statement layout:
//   Cuenta,<n>,Moneda,MXN,Periodo,01/07/2026 al 31/07/2026,Saldo inicial,<amount>
//   Fecha,Concepto,Referencia,Clave de rastreo,Cargo,Abono,Saldo
import { decimalToCents } from './text'

export function parseCsvLine(line: string, sep = ','): string[] {
  const out: string[] = []
  let cur = ''
  let quoted = false
  for (let i = 0; i < line.length; i++) {
    const c = line[i]
    if (quoted) {
      if (c === '"' && line[i + 1] === '"') {
        cur += '"'
        i++
      } else if (c === '"') quoted = false
      else cur += c
    } else if (c === '"') quoted = true
    else if (c === sep) {
      out.push(cur)
      cur = ''
    } else cur += c
  }
  out.push(cur)
  return out
}

export function parseCsv(text: string, sep = ','): string[][] {
  return text
    .split('\n')
    .map((l) => l.replace(/\r$/, ''))
    .filter((l) => l.trim() !== '')
    .map((l) => parseCsvLine(l, sep))
}

export interface MxCsvMovement {
  bookingDate: string
  concept: string
  reference: string
  trackingKey: string
  /** Signed cents: abono − cargo. */
  amount: number
  balance: number | null
  raw: string
}

export interface MxCsvStatement {
  account: string | null
  currency: string | null
  period: string | null
  opening: number | null
  closing: number | null
  movements: MxCsvMovement[]
  warnings: string[]
}

const dmy = (s: string) => {
  const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(s.trim())
  return m ? `${m[3]}-${m[2]}-${m[1]}` : s.trim()
}

export function parseMxCsv(text: string): MxCsvStatement {
  const lines = text
    .split('\n')
    .map((l) => l.replace(/\r$/, ''))
    .filter((l) => l.trim() !== '')
  const warnings: string[] = []
  const meta = new Map<string, string>()
  let headerAt = lines.findIndex((l) => /^fecha\s*,/i.test(l))
  if (headerAt === -1) {
    warnings.push('CSV sin cabecera «Fecha,Concepto,…»')
    headerAt = lines.length
  }
  for (const l of lines.slice(0, headerAt)) {
    const cells = parseCsvLine(l)
    for (let i = 0; i + 1 < cells.length; i += 2) meta.set(cells[i].trim().toLowerCase(), cells[i + 1].trim())
  }
  const header = headerAt < lines.length ? parseCsvLine(lines[headerAt]).map((h) => h.trim().toLowerCase()) : []
  const col = (name: string) => header.findIndex((h) => h.startsWith(name))
  const [iDate, iConcept, iRef, iTrack, iDebit, iCredit, iBalance] = ['fecha', 'concepto', 'referencia', 'clave', 'cargo', 'abono', 'saldo'].map(col)
  const movements: MxCsvMovement[] = []
  for (const raw of lines.slice(headerAt + 1)) {
    const c = parseCsvLine(raw)
    const debit = decimalToCents(c[iDebit] || '0')
    const credit = decimalToCents(c[iCredit] || '0')
    const balance = iBalance >= 0 && c[iBalance] ? decimalToCents(c[iBalance]) : null
    if (Number.isNaN(debit) || Number.isNaN(credit)) {
      warnings.push(`Importe ilegible: ${raw}`)
      continue
    }
    movements.push({
      bookingDate: dmy(c[iDate] ?? ''),
      concept: (c[iConcept] ?? '').trim(),
      reference: (c[iRef] ?? '').trim(),
      trackingKey: (c[iTrack] ?? '').trim(),
      amount: credit - debit,
      balance: balance === null || Number.isNaN(balance) ? null : balance,
      raw,
    })
  }
  const openingText = meta.get('saldo inicial')
  const opening = openingText ? decimalToCents(openingText) : null
  const closing = movements.length ? movements[movements.length - 1].balance : opening
  if (opening !== null && closing !== null) {
    const expected = opening + movements.reduce((s, m) => s + m.amount, 0)
    if (expected !== closing) warnings.push(`Saldo final ${closing} ≠ inicial + movimientos (${expected})`)
  }
  return {
    account: meta.get('cuenta') ?? null,
    currency: meta.get('moneda') ?? null,
    period: meta.get('periodo') ?? null,
    opening,
    closing,
    movements,
    warnings,
  }
}
