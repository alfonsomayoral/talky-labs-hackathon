// Raw statement (N43 / CAMT.053 / CSV) → RawBankDetail per `<month>.lines.jsonl` row.
import type { BankLine, RawBankDetail, StatementFormat } from '@/domain/types'
import { parseCamt053 } from './camt053'
import { parseMxCsv } from './csv'
import { parseN43 } from './n43'

export interface RawMovement {
  /** Explicit bank_line id when the format carries it (CAMT NtryRef). */
  id: string | null
  amount: number
  bookingDate: string | null
  valueDate: string | null
  raw: string[]
  concepts: string[]
  references: Record<string, string>
}

export interface RawStatement {
  movements: RawMovement[]
  opening: number | null
  closing: number | null
  warnings: string[]
}

export interface MappedStatement {
  details: RawBankDetail[]
  opening: number | null
  closing: number | null
  warnings: string[]
}

const compact = (r: Record<string, string | null | undefined>) =>
  Object.fromEntries(Object.entries(r).filter((e): e is [string, string] => !!e[1]))

export function statementFormat(path: string): StatementFormat | null {
  if (path.endsWith('.n43')) return 'n43'
  if (path.endsWith('.camt053.xml') || path.endsWith('.xml')) return 'camt053'
  if (path.endsWith('.csv')) return 'csv'
  return null
}

export function parseRawStatement(format: StatementFormat, text: string): RawStatement {
  if (format === 'n43') {
    const f = parseN43(text)
    return {
      movements: f.movements.map((m) => ({
        id: null,
        amount: m.amount,
        bookingDate: m.bookingDate,
        valueDate: m.valueDate,
        raw: m.raw,
        concepts: m.concepts,
        references: compact({
          oficina: m.office,
          concepto_comun: m.commonConcept,
          concepto_propio: m.ownConcept,
          documento: m.documentNumber,
          referencia_1: m.reference1,
          referencia_2: m.reference2,
          divisa_origen: m.fx?.currency,
          importe_origen: m.fx ? (m.fx.amount / 100).toFixed(2) : null,
        }),
      })),
      opening: f.accounts[0]?.opening ?? null,
      closing: f.accounts.length ? f.accounts[f.accounts.length - 1].closing : null,
      warnings: f.warnings,
    }
  }
  if (format === 'camt053') {
    const s = parseCamt053(text)
    return {
      movements: s.entries.map((e) => ({
        id: e.entryRef,
        amount: e.amount,
        bookingDate: e.bookingDate,
        valueDate: e.valueDate,
        raw: [e.raw],
        concepts: e.unstructured,
        references: compact({
          NtryRef: e.entryRef,
          AcctSvcrRef: e.accountServicerRef,
          EndToEndId: e.endToEndIds.join(' · '),
          InstrId: e.instructionIds.join(' · '),
          BkTxCd: e.bankTxCode,
          Contraparte: e.counterparty,
          Ref: e.structuredRefs.join(' · '),
        }),
      })),
      opening: s.opening,
      closing: s.closing,
      warnings: s.warnings,
    }
  }
  const s = parseMxCsv(text)
  return {
    movements: s.movements.map((m) => ({
      id: null,
      amount: m.amount,
      bookingDate: m.bookingDate,
      valueDate: null,
      raw: [m.raw],
      concepts: [m.concept],
      references: compact({ Referencia: m.reference, 'Clave de rastreo': m.trackingKey }),
    })),
    opening: s.opening,
    closing: s.closing,
    warnings: s.warnings,
  }
}

/**
 * Pairs raw movements with the statement lines: by explicit id when every movement has one
 * that exists in `lines`, otherwise by order. Count, amount and date differences become warnings.
 */
export function mapToLines(raw: RawStatement, lines: BankLine[], label: string): MappedStatement {
  const warnings = raw.warnings.map((w) => `${label}: ${w}`)
  const byId = new Map(lines.map((l) => [l.bank_line, l]))
  const useIds = raw.movements.length > 0 && raw.movements.every((m) => m.id && byId.has(m.id))
  if (raw.movements.length !== lines.length)
    warnings.push(`${label}: ${raw.movements.length} movimientos en el extracto y ${lines.length} en lines.jsonl`)

  const details: RawBankDetail[] = []
  const mismatches: string[] = []
  raw.movements.forEach((m, i) => {
    const line = useIds ? byId.get(m.id!) : lines[i]
    if (!line) return
    if (line.amount !== m.amount) mismatches.push(`${line.bank_line} importe ${m.amount} ≠ ${line.amount}`)
    else if (m.bookingDate && line.booking_date !== m.bookingDate) mismatches.push(`${line.bank_line} fecha ${m.bookingDate} ≠ ${line.booking_date}`)
    else if (m.valueDate && line.value_date !== m.valueDate) mismatches.push(`${line.bank_line} fecha valor ${m.valueDate} ≠ ${line.value_date}`)
    details.push({ bank_line: line.bank_line, raw: m.raw, concepts: m.concepts, references: m.references })
  })
  if (mismatches.length)
    warnings.push(`${label}: ${mismatches.length} líneas no coinciden con lines.jsonl (${mismatches.slice(0, 3).join('; ')}${mismatches.length > 3 ? '…' : ''})`)

  const net = lines.reduce((s, l) => s + l.amount, 0)
  if (raw.opening !== null && raw.closing !== null && raw.opening + net !== raw.closing)
    warnings.push(`${label}: saldo inicial + líneas (${raw.opening + net}) ≠ saldo final del extracto (${raw.closing})`)
  return { details, opening: raw.opening, closing: raw.closing, warnings }
}
