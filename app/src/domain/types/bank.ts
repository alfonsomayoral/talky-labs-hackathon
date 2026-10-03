// Bank statements under `<phase>/bank/<account>/<YYYY-MM>.*`.

import type { Cents, IsoDate } from './erp'
import type { DatasetPath } from './inbox'

/** One row of `<YYYY-MM>.lines.jsonl` — the statement line with its id. */
export interface BankLine {
  bank_line: string
  booking_date: IsoDate
  value_date: IsoDate
  /** Signed cents in the account currency: positive = credit to the account. */
  amount: Cents
  currency: string
  /** Truncated text (≈45 chars). The raw statement carries the full references. */
  text: string
}

export type StatementFormat = 'n43' | 'camt053' | 'csv'

/** Details recovered from the raw statement (Norma 43 record 23, CAMT Ustrd/Refs, CSV columns). */
export interface RawBankDetail {
  bank_line: string
  /** Raw source records for evidence display (e.g. the 80-char N43 records 22 + 23). */
  raw: string[]
  concepts: string[]
  references: Record<string, string>
}

export interface BankStatement {
  account: string
  month: string
  format: StatementFormat
  lines: BankLine[]
  rawPath: DatasetPath | null
  opening?: Cents
  closing?: Cents
}
