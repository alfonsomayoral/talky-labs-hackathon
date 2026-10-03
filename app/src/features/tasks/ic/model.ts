// Pure helpers behind /tareas/intragrupo: the company × company matrix, both books of a pair and the loan interest check.

import type { Cents, IntercompanyAgreements, JournalEntry, WorkItem } from '@/domain/types'
import type { ToEur } from '@/engine'
import { loanInterest } from '@/features/item/kit'

export const pairKey = (pair: readonly string[]) => [...pair].map(String).sort().join('-')
export const pairOfItem = (item: Pick<WorkItem, 'key'>) => item.key.slice(0, item.key.indexOf('/'))

// ---------------------------------------------------------------- matrix

export interface PairCell {
  pair: string
  items: WorkItem[]
  /** Σ|difference| of its items in EUR cents. */
  eur: Cents
}

export interface IcMatrix {
  companies: string[]
  /** Only the pairs of tasks/intercompany.json (and any pair an item names), keyed by `a-b`. */
  cells: Map<string, PairCell>
}

export function icMatrix(pairs: readonly (readonly string[])[], items: readonly WorkItem[], eurOf: (item: WorkItem) => Cents): IcMatrix {
  const cells = new Map<string, PairCell>()
  const cell = (key: string) => {
    let c = cells.get(key)
    if (!c) cells.set(key, (c = { pair: key, items: [], eur: 0 }))
    return c
  }
  for (const p of pairs) cell(pairKey(p))
  for (const it of items) {
    const c = cell(pairOfItem(it))
    c.items.push(it)
    c.eur += Math.abs(eurOf(it))
  }
  const companies = [...new Set([...cells.keys()].flatMap((k) => k.split('-')))].sort()
  return { companies, cells }
}

// ---------------------------------------------------------------- both books

export interface BookLine {
  entry: string
  date: string
  reference: string
  account: string
  partner: string | null
  /** Signed (debit +, credit −) in the company currency. */
  local: Cents
  /** Signed in the document currency when it differs from the company's (EUR lines of 3100). */
  doc: { currency: string; amount: Cents } | null
  /** Signed EUR cents: the document amount for EUR lines, otherwise the local amount at the month-end rate. */
  eur: Cents
  text: string
  /** The partner does not point to the other company of the pair. */
  wrongPartner: boolean
}

export interface BookSide {
  company: string
  lines: BookLine[]
  /** Net EUR per account with the other company (lines with a wrong partner left out), in account order. */
  totals: { account: string; eur: Cents }[]
}

/** `1000` and `V-IC1000` both name company 1000 as a partner. */
const partnerCompany = (partner: string | null) => (partner?.startsWith('V-IC') ? partner.slice(4) : partner)

/**
 * In-month lines of each company of the pair on the intercompany accounts: the ones whose partner is the
 * other company, plus the ones that mirror a line of the other side (same reference and amount) but name
 * a different partner. Month-end FX valuations (CLOSE_FX and their reversals) are left out: they only
 * restate 3100's MXN balance.
 */
export function pairBooks(pair: readonly [string, string], entries: readonly JournalEntry[], accounts: readonly string[], currencyOf: (company: string) => string, toEur: ToEur): [BookSide, BookSide] {
  const ic = new Set(accounts)
  const pick = (company: string, other: string, mirrors: Map<string, Set<Cents>> | null) => {
    const lines: BookLine[] = []
    for (const e of entries) {
      if (e.company !== company || e.source.startsWith('CLOSE_FX')) continue
      for (const l of e.lines) {
        if (!ic.has(l.account)) continue
        const local = (l.debit || 0) - (l.credit || 0)
        const sign = Math.sign(local) || 1
        const eur = l.currency === 'EUR' ? sign * Math.abs(l.amount_doc) : toEur(company, local)
        const toOther = partnerCompany(l.partner) === other
        if (!toOther && !mirrors?.get(e.reference)?.has(Math.abs(eur))) continue
        const foreign = l.currency && l.currency !== currencyOf(company)
        lines.push({
          entry: e.id,
          date: e.posting_date,
          reference: e.reference,
          account: l.account,
          partner: l.partner,
          local,
          doc: foreign ? { currency: l.currency, amount: sign * Math.abs(l.amount_doc) } : null,
          eur,
          text: l.text,
          wrongPartner: !toOther,
        })
      }
    }
    return lines.sort((a, b) => a.date.localeCompare(b.date) || a.entry.localeCompare(b.entry))
  }
  const mirrorsOf = (lines: BookLine[]) => {
    const m = new Map<string, Set<Cents>>()
    for (const l of lines) if (!l.wrongPartner) m.set(l.reference, (m.get(l.reference) ?? new Set()).add(Math.abs(l.eur)))
    return m
  }
  const [a, b] = pair
  const linesB = pick(b, a, mirrorsOf(pick(a, b, null)))
  const linesA = pick(a, b, mirrorsOf(linesB))
  return [side(a, linesA), side(b, linesB)]
}

function side(company: string, lines: BookLine[]): BookSide {
  const totals = new Map<string, Cents>()
  for (const l of lines) if (!l.wrongPartner) totals.set(l.account, (totals.get(l.account) ?? 0) + l.eur)
  return { company, lines, totals: [...totals].sort(([x], [y]) => x.localeCompare(y)).map(([account, eur]) => ({ account, eur })) }
}

// ---------------------------------------------------------------- loan interest (act/360)

export interface InterestCheck {
  days: number
  /** EUR cents the policy expects: principal × rate × days / 360. */
  expected: Cents
  thirty: Cents
  /** EUR cents each side booked for the month (null when the side has no interest line). */
  lender: Cents | null
  borrower: Cents | null
}

export function interestCheck(loan: IntercompanyAgreements['loan'], month: string, books: readonly BookSide[]): InterestCheck {
  const [y, m] = month.split('-').map(Number)
  const days = new Date(Date.UTC(y, m, 0)).getUTCDate()
  const interest = (d: number) => loanInterest(loan.principal, loan.rate_bp, d)
  const ref = `KMI-INT-${month.replace('-', '')}`
  const booked = (company: string) => {
    const lines = books.find((s) => s.company === company)?.lines.filter((l) => l.reference === ref && l.account === '55200000') ?? []
    return lines.length ? Math.abs(lines.reduce((s, l) => s + l.eur, 0)) : null
  }
  return { days, expected: interest(days), thirty: interest(30), lender: booked(loan.lender), borrower: booked(loan.borrower) }
}
