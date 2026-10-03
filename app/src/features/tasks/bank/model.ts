// Bank reconciliation view model: pure functions over bank_rec.jsonl, the statements and the 572 journal lines.

import type { ApRow, BankAccount, BankCategory, BankLine, BankRecRow, BankStatement, JournalEntry, JournalLine, WorkItem } from '@/domain/types'
import { BANK_CATEGORY_CATALOG } from '@/domain/catalog/policy'
import type { Tone } from '@/components'

// ---------------------------------------------------------------- book lines on the bank's GL account
export interface BookLine {
  /** `<entry id>#<line>` as in bank_rec.jsonl. */
  id: string
  date: string
  /** Signed, in the account currency: + = debit to 572 (money in), like the statement. */
  amount: number
  text: string
  partner: string | null
  source: string
}

/**
 * Amount of a 572 line in the bank account's currency. Local-currency accounts use debit − credit; a
 * foreign-currency account (3100 USD) uses the document amount of its lines in that currency, and its
 * local valuation lines (no foreign amount) are not bank movements: null.
 */
export function bookAmount(line: Pick<JournalLine, 'debit' | 'credit' | 'currency' | 'amount_doc'>, accountCurrency: string, companyCurrency: string): number | null {
  const sign = line.debit - line.credit >= 0 ? 1 : -1
  if (accountCurrency === companyCurrency) return line.debit - line.credit
  return line.currency === accountCurrency ? sign * Math.abs(line.amount_doc) : null
}

/** The lines of `entries` posted to the account's GL in its company, in the account currency. */
export function bookLinesOf(entries: readonly JournalEntry[], account: Pick<BankAccount, 'company' | 'gl_account' | 'currency'>, companyCurrency: string): BookLine[] {
  const out: BookLine[] = []
  for (const e of entries) {
    if (e.company !== account.company) continue
    for (const l of e.lines) {
      if (l.account !== account.gl_account) continue
      const amount = bookAmount(l, account.currency, companyCurrency)
      if (amount === null) continue
      out.push({ id: `${e.id}#${l.line}`, date: e.posting_date, amount, text: l.text || e.header_text, partner: l.partner, source: e.source })
    }
  }
  return out
}

// ---------------------------------------------------------------- matches, unmatched and blocks for the face-to-face view
export type MatchShape = '1:1' | 'N:1' | '1:N' | 'N:M'

export function matchShape(bank: number, book: number): MatchShape {
  if (bank <= 1 && book <= 1) return '1:1'
  if (book <= 1) return 'N:1'
  if (bank <= 1) return '1:N'
  return 'N:M'
}

export interface RecLine {
  id: string
  side: 'bank' | 'book'
  date: string | null
  amount: number | null
  text: string
  /** Index of its match in row.matches, or null. */
  group: number | null
  /** Category of an unmatched line (or of a difference match). */
  category: string | null
  /** False for referenced lines outside the statement or the month (e.g. prior-period items). */
  known: boolean
}

export interface RecGroup {
  index: number
  shape: MatchShape
  bank: RecLine[]
  book: RecLine[]
  /** Σ bank − Σ book (0 for an exact match). */
  diff: number
  category: string | null
}

export type RecBlock =
  | { kind: 'match'; group: RecGroup; date: string | null }
  | { kind: 'bank'; line: RecLine; date: string | null }
  | { kind: 'book'; line: RecLine; date: string | null }

export interface RecView {
  groups: RecGroup[]
  /** Blocks in date order: a match with its lines on both sides, or a lone unmatched line. */
  blocks: RecBlock[]
  /** Statement lines the deliverable does not mention. */
  untreatedBank: RecLine[]
  /** Month book lines on the GL the deliverable does not mention. */
  untreatedBook: RecLine[]
}

const sum = (xs: readonly (number | null)[]) => xs.reduce<number>((s, x) => s + (x ?? 0), 0)

export function recView(row: BankRecRow, bankLines: readonly BankLine[], monthBook: readonly BookLine[], referencedBook: readonly BookLine[]): RecView {
  const bankById = new Map(bankLines.map((b) => [b.bank_line, b]))
  const bookById = new Map([...referencedBook, ...monthBook].map((b) => [b.id, b]))
  const used = new Set<string>()
  const bankLine = (id: string, group: number | null, category: string | null): RecLine => {
    used.add(`bank:${id}`)
    const b = bankById.get(id)
    return { id, side: 'bank', date: b?.booking_date ?? null, amount: b?.amount ?? null, text: b?.text ?? '', group, category, known: !!b }
  }
  const bookLine = (id: string, group: number | null, category: string | null): RecLine => {
    used.add(`book:${id}`)
    const b = bookById.get(id)
    return { id, side: 'book', date: b?.date ?? null, amount: b?.amount ?? null, text: b?.text ?? '', group, category, known: !!b }
  }

  const groups = (row.matches ?? []).map((m, index): RecGroup => {
    const category = m.category && m.category !== 'MATCH' ? String(m.category) : null
    const bank = (m.bank_lines ?? []).map((id) => bankLine(String(id), index, category))
    const book = (m.book_lines ?? []).map((id) => bookLine(String(id), index, category))
    return { index, shape: matchShape(bank.length, book.length), bank, book, diff: sum(bank.map((l) => l.amount)) - sum(book.map((l) => l.amount)), category }
  })
  const lonelyBank = (row.unmatched_bank ?? []).map((u) => bankLine(String(u.bank_line), null, String(u.category)))
  const lonelyBook = (row.unmatched_book ?? []).map((u) => bookLine(String(u.book_line), null, String(u.category)))

  const minDate = (ls: RecLine[]) => ls.map((l) => l.date).filter((d): d is string => !!d).sort()[0] ?? null
  const blocks: RecBlock[] = [
    ...groups.map((group): RecBlock => ({ kind: 'match', group, date: minDate([...group.bank, ...group.book]) })),
    ...lonelyBank.map((line): RecBlock => ({ kind: 'bank', line, date: line.date })),
    ...lonelyBook.map((line): RecBlock => ({ kind: 'book', line, date: line.date })),
  ]
  const order = { match: 0, bank: 1, book: 2 }
  blocks.sort((a, b) => (a.date ?? '9999').localeCompare(b.date ?? '9999') || order[a.kind] - order[b.kind])

  const untreatedBank = bankLines.filter((b) => !used.has(`bank:${b.bank_line}`)).map((b) => bankLine(b.bank_line, null, null))
  const untreatedBook = monthBook.filter((b) => !used.has(`book:${b.id}`)).map((b) => bookLine(b.id, null, null))
  return { groups, blocks, untreatedBank, untreatedBook }
}

/** Every book line id the row mentions, to resolve them with getJournalEntries. */
export function referencedBookLines(row: BankRecRow): string[] {
  return [...new Set([...(row.matches ?? []).flatMap((m) => (m.book_lines ?? []).map(String)), ...(row.unmatched_book ?? []).map((u) => String(u.book_line))])]
}

export const entryIdOf = (bookLine: string) => bookLine.slice(0, bookLine.lastIndexOf('#'))

// ---------------------------------------------------------------- unmatched by category and adjustments
export interface CategoryGroup {
  category: string
  label: string
  section: string | null
  side: 'bank' | 'book' | 'both' | 'difference' | null
  /** The policy expects an adjusting entry for this category. */
  expectsAdjustment: boolean
  /** An adjustment of this category moves this 572. */
  adjusted: boolean
  /**
   * Effect on the 572 of these lines that no adjustment covers (adjustments do not name their lines, and one can
   * cover several, e.g. a returned direct debit and its fee). Null when the adjustments are in another currency.
   */
  uncovered: number | null
  lines: RecLine[]
  amount: number
}

/**
 * `adjustments`: those that move this account's 572, from any row (see `glAdjustments`).
 * `sameCurrency`: the adjustments are in the account's currency (not so for the 3100 USD account).
 */
export function unmatchedByCategory(view: RecView, adjustments: readonly AdjustmentView[], sameCurrency: boolean): CategoryGroup[] {
  const byCat = new Map<string, RecLine[]>()
  for (const b of view.blocks) {
    if (b.kind === 'match') continue
    const k = b.line.category ?? 'SIN_CATEGORIA'
    byCat.set(k, [...(byCat.get(k) ?? []), b.line])
  }
  return [...byCat].map(([category, lines]) => {
    const entry = BANK_CATEGORY_CATALOG[category as BankCategory]
    const own = adjustments.filter((a) => a.category === category)
    const effect = sum(lines.map((l) => (l.side === 'bank' ? l.amount : l.amount === null ? null : -l.amount)))
    return {
      category,
      label: entry?.label ?? category,
      section: entry?.section ?? null,
      side: entry?.side ?? null,
      expectsAdjustment: entry?.adjustment ?? false,
      adjusted: own.length > 0,
      uncovered: sameCurrency ? effect - sum(own.map((a) => a.glMovement)) : null,
      lines,
      amount: sum(lines.map((l) => l.amount)),
    }
  })
}

export interface OpenDirectDebit {
  line: RecLine
  /** AP document of the same amount in the company, if any. */
  invoice: ApRow | null
  /** AP posted the invoice, so the debit should have been adjusted against the vendor. */
  missing: boolean
}

const POSTED = new Set(['POST', 'POST_PAYMENT_BLOCK'])

/**
 * Direct debits of the statement that no adjustment covers, each with the AP invoice of the same amount. An adjustment
 * is only due when AP posted that invoice; a rejected or absent invoice leaves the debit open on purpose.
 */
export function openDirectDebits(lines: readonly RecLine[], adjustments: readonly AdjustmentView[], apRows: readonly ApRow[], company: string, currency: string): OpenDirectDebit[] {
  const pending = adjustments.filter((a) => a.category === 'DIRECT_DEBIT_NOT_BOOKED').map((a) => a.glMovement)
  const out: OpenDirectDebit[] = []
  for (const line of lines) {
    const amount = line.amount
    if (line.side !== 'bank' || line.category !== 'DIRECT_DEBIT_NOT_BOOKED' || amount === null) continue
    const covered = pending.indexOf(amount)
    if (covered >= 0) {
      pending.splice(covered, 1)
      continue
    }
    const same = apRows.filter((r) => r.company === company && r.gross === -amount && (r.currency ?? currency) === currency)
    const invoice = same.find((r) => POSTED.has(r.decision)) ?? same[0] ?? null
    out.push({ line, invoice, missing: !!invoice && POSTED.has(invoice.decision) })
  }
  return out
}

export interface AdjustmentView {
  /** Bank account whose bank_rec row carries the adjustment. */
  account: string
  index: number
  category: string
  label: string
  /** Effect on the bank GL account (Σ debit − credit of its lines on the 572 of this company). */
  glMovement: number
  lines: BankRecRow['adjustments'][number]['lines']
}

export function adjustmentsOf(row: BankRecRow, glAccount: string, company: string = row.company): AdjustmentView[] {
  return (row.adjustments ?? []).map((a, index) => {
    const lines = Array.isArray(a.lines) ? a.lines : []
    const onGl = lines.filter((l) => l.account === glAccount && (l.company ?? row.company) === company)
    return {
      account: row.account,
      index,
      category: String(a.category),
      label: BANK_CATEGORY_CATALOG[a.category as BankCategory]?.label ?? String(a.category),
      glMovement: onGl.reduce((s, l) => s + (l.debit ?? 0) - (l.credit ?? 0), 0),
      lines,
    }
  })
}

/**
 * Adjustments of every row that move this company's 572: a reclassification between bank accounts
 * (WRONG_BANK_ACCOUNT) sits in one account's row but moves both GL accounts.
 */
export function glAdjustments(rows: readonly BankRecRow[], company: string, glAccount: string): AdjustmentView[] {
  return rows.flatMap((r) => adjustmentsOf(r, glAccount, company).filter((a) => a.glMovement !== 0))
}

// ---------------------------------------------------------------- balance bridge statement → book
export interface BridgeStep {
  id: string
  label: string
  amount: number
  kind: 'total' | 'step'
  detail: string | null
}

export interface BridgeInput {
  statementOpening: number | null
  statementClosing: number | null
  /** Σ of the month's statement lines (closing = opening + this). */
  statementMovement: number
  /** GL balance at month end, in the account currency. */
  glClosing: number
  /** Σ of the month's GL lines. */
  glMovement: number
  view: RecView
  /** Null when the adjustments are posted in another currency (3100 USD: in MXN), so they stay out of the bridge. */
  adjustments: readonly AdjustmentView[] | null
}

/**
 * Statement closing → book closing, then book after the adjustments. Every step is a sum of
 * listed lines; the opening difference is the gap the month inherits (prior-month items).
 */
export function balanceBridge(input: BridgeInput): BridgeStep[] {
  const { view } = input
  const closing = input.statementClosing ?? (input.statementOpening ?? 0) + input.statementMovement
  const opening = input.statementOpening ?? closing - input.statementMovement
  const glOpening = input.glClosing - input.glMovement
  const lone = (side: 'bank' | 'book') => view.blocks.flatMap((b) => (b.kind === side ? [b.line] : []))
  const bankOnly = sum(lone('bank').map((l) => l.amount))
  const bookOnly = sum(lone('book').filter((l) => l.known).map((l) => l.amount))
  const inMatches = sum(view.groups.map((g) => g.diff))
  const untreated = sum(view.untreatedBank.map((l) => l.amount)) - sum(view.untreatedBook.map((l) => l.amount))
  const openingDiff = opening - glOpening
  const explained = closing - bankOnly + bookOnly - inMatches - untreated - openingDiff
  const adjust = sum((input.adjustments ?? []).map((a) => a.glMovement))
  const steps: BridgeStep[] = [
    { id: 'statement', label: 'Saldo del extracto al cierre', amount: closing, kind: 'total', detail: null },
    { id: 'bank_only', label: 'Partidas solo en el banco', amount: -bankOnly, kind: 'step', detail: `${lone('bank').length} líneas sin casar del extracto` },
    { id: 'book_only', label: 'Partidas solo en el libro', amount: bookOnly, kind: 'step', detail: `${lone('book').length} apuntes sin casar` },
    { id: 'in_matches', label: 'Diferencias dentro de casaciones', amount: -inMatches, kind: 'step', detail: `${view.groups.filter((g) => g.diff !== 0).length} casaciones con diferencia` },
    { id: 'opening', label: 'Diferencia de apertura', amount: -openingDiff, kind: 'step', detail: 'Saldo inicial del extracto frente al del libro' },
    { id: 'untreated', label: 'Líneas del mes sin tratar', amount: -untreated, kind: 'step', detail: `${view.untreatedBank.length} del extracto y ${view.untreatedBook.length} del libro no figuran en la conciliación` },
    { id: 'gap', label: 'Sin explicar', amount: input.glClosing - explained, kind: 'step', detail: null },
    { id: 'book', label: 'Saldo contable al cierre', amount: input.glClosing, kind: 'total', detail: null },
  ]
  if (input.adjustments)
    steps.push(
      { id: 'adjustments', label: 'Ajustes propuestos', amount: adjust, kind: 'step', detail: `${input.adjustments.length} asientos de ajuste` },
      { id: 'book_after', label: 'Saldo contable tras ajustes', amount: input.glClosing + adjust, kind: 'total', detail: null },
      { id: 'residual', label: 'Diferencia con el extracto', amount: closing - (input.glClosing + adjust), kind: 'total', detail: 'Lo que queda abierto: partidas sin ajuste (en tránsito, error del banco…) y la apertura' },
    )
  return steps.filter((s) => s.kind === 'total' || s.amount !== 0 || s.id === 'bank_only' || s.id === 'book_only')
}

// ---------------------------------------------------------------- account grid
export type AccountStatus = 'missing' | 'reconciled' | 'open'

export const ACCOUNT_STATUS: Record<AccountStatus, { label: string; tone: Tone }> = {
  reconciled: { label: 'Conciliada', tone: 'ok' },
  open: { label: 'Con partidas sin explicar', tone: 'warn' },
  missing: { label: 'Sin conciliar', tone: 'neutral' },
}

export interface AccountSummary {
  account: BankAccount
  row: BankRecRow | null
  status: AccountStatus
  opening: number | null
  closing: number | null
  statementLines: number
  matchedBankLines: number
  matches: number
  unmatchedBank: number
  unmatchedBook: number
  adjustments: number
  /** Items without an adjustment (open), with their amount. */
  open: number
  openAmount: number
}

/**
 * An account is reconciled when every open item is explained: its category needs no adjustment
 * (in transit, bank error…) or the adjustment is delivered, in any row of the company (as the
 * overview's bank control). `rows` are all bank_rec rows; WRONG_BANK_ACCOUNT books in another account.
 */
export function accountSummary(
  account: BankAccount,
  row: BankRecRow | null,
  statement: BankStatement | null,
  items: readonly WorkItem[],
  rows: readonly BankRecRow[] = row ? [row] : [],
): AccountSummary {
  const lines = statement?.lines ?? []
  const own = items.filter((it) => it.task === 'bank_rec' && it.key.startsWith(`${account.id}/`))
  const open = own.filter((it) => it.status === 'OPEN')
  const adjusted = new Set(rows.flatMap((r) => (r.adjustments ?? []).map((a) => `${r.company}|${a.category}`)))
  const unexplained = open.filter((it) => {
    const entry = BANK_CATEGORY_CATALOG[it.outcome as BankCategory]
    return !entry || (entry.adjustment && !adjusted.has(`${it.company}|${it.outcome}`))
  })
  const inMonth = new Set(lines.map((l) => l.bank_line))
  const matchedBank = new Set((row?.matches ?? []).flatMap((m) => (m.bank_lines ?? []).map(String)).filter((id) => inMonth.has(id)))
  return {
    account,
    row,
    status: !row ? 'missing' : unexplained.length ? 'open' : 'reconciled',
    opening: statement?.opening ?? null,
    closing: statement?.closing ?? (statement ? (statement.opening ?? 0) + sum(lines.map((l) => l.amount)) : null),
    statementLines: lines.length,
    matchedBankLines: matchedBank.size,
    matches: row?.matches?.length ?? 0,
    unmatchedBank: row?.unmatched_bank?.length ?? 0,
    unmatchedBook: row?.unmatched_book?.length ?? 0,
    adjustments: row?.adjustments?.length ?? 0,
    open: open.length,
    openAmount: sum(open.map((it) => it.amount)),
  }
}

/** Map from a bank line or book line id of this account to the WorkItem that holds it (for the peek). */
export function itemByLine(items: readonly WorkItem[], account: string): Map<string, string> {
  const out = new Map<string, string>()
  for (const it of items) {
    if (it.task !== 'bank_rec' || !it.key.startsWith(`${account}/`)) continue
    for (const ev of it.evidence) {
      if (ev.kind === 'bank') out.set(ev.bank_line, it.id)
      else if (ev.kind === 'journal') out.set(ev.book_line, it.id)
    }
  }
  return out
}
