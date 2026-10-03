// Building blocks of score.py: norm_num, je_lines, norm_line, je_match, f1, amount_ok.

import { get, intOr0, isDict, or, pyInt, pyStr, truthy, tupleKey } from './py'

export function normNum(s: unknown): string {
  const str = truthy(s) ? pyStr(s) : ''
  return str.toUpperCase().replace(/[^0-9A-Z]/g, '').replace(/^0+/, '')
}

/** One journal line as score.py sees it: signed amount = debit − credit (zero lines dropped). */
export interface PyJeLine {
  company: unknown
  account: string
  amount: number
  partner: unknown
  cost_center: unknown
  wbs: unknown
}

/** `je_lines(je, company)`: accepts `{company, lines}` or a bare list of lines. */
export function jeLines(je: unknown, company: unknown = null): PyJeLine[] {
  if (!truthy(je)) return []
  const lines = isDict(je) ? ('lines' in je ? je.lines : null) : je
  if (!Array.isArray(lines)) return []
  const jeCompany = isDict(je) ? get(je, 'company') : null
  const out: PyJeLine[] = []
  for (const l of lines) {
    if (!isDict(l)) continue
    const amount = intOr0(get(l, 'debit')) - intOr0(get(l, 'credit'))
    if (!amount) continue
    out.push({
      company: or(get(l, 'company'), company, jeCompany),
      account: pyStr(l.account),
      amount,
      partner: get(l, 'partner'),
      cost_center: or(get(l, 'cost_center'), null),
      wbs: or(get(l, 'wbs'), null),
    })
  }
  return out
}

const PARTNER_PREFIXES = ['40', '41', '43', '44', '49', '55', '24', '16']
const COST_PREFIXES = ['6', '7', '2']

/** A line normalised for matching: partner only on open-item accounts, cost object only on P&L/assets. */
export interface NormLine {
  account: string
  amount: number
  partner: unknown
  cost_center: unknown
  wbs: unknown
}

export function normLine(l: PyJeLine): NormLine {
  const acc = l.account
  const partner = PARTNER_PREFIXES.some((p) => acc.startsWith(p)) ? l.partner : null
  const cost = COST_PREFIXES.some((p) => acc.startsWith(p))
  return { account: acc, amount: l.amount, partner, cost_center: cost ? l.cost_center : null, wbs: cost ? l.wbs : null }
}

export interface JeMatchDetail {
  score: number
  hits: number
  /** Gold lines without a counterpart within tolerance. */
  missing: NormLine[]
  /** Submitted lines left over after matching. */
  extra: NormLine[]
}

/** Greedy line matching on (account, partner, cost centre, WBS) with ±tol cents: hits / max(lines). */
export function jeMatchDetail(gold: unknown, sub: unknown, company: unknown = null, tol = 2): JeMatchDetail {
  const g = jeLines(gold, company).map(normLine)
  const s = jeLines(sub, company).map(normLine)
  if (!g.length && !s.length) return { score: 1.0, hits: 0, missing: [], extra: [] }
  const pool = new Map<string, NormLine[]>()
  for (const x of s) {
    const k = tupleKey(x.account, x.partner, x.cost_center, x.wbs)
    const list = pool.get(k)
    if (list) list.push(x)
    else pool.set(k, [x])
  }
  let hit = 0
  const missing: NormLine[] = []
  for (const x of g) {
    const cand = pool.get(tupleKey(x.account, x.partner, x.cost_center, x.wbs)) ?? []
    let best = -1
    for (let i = 0; i < cand.length; i++) {
      if (best < 0 || Math.abs(cand[i].amount - x.amount) < Math.abs(cand[best].amount - x.amount)) best = i
    }
    if (best >= 0 && Math.abs(cand[best].amount - x.amount) <= tol) {
      cand.splice(best, 1)
      hit += 1
    } else missing.push(x)
  }
  const extra = [...pool.values()].flat()
  return { score: hit / Math.max(g.length, s.length), hits: hit, missing, extra }
}

export const jeMatch = (gold: unknown, sub: unknown, company: unknown = null, tol = 2): number =>
  jeMatchDetail(gold, sub, company, tol).score

export function f1(tp: number, fp: number, fn: number): number {
  const p = tp + fp ? tp / (tp + fp) : 1.0
  const r = tp + fn ? tp / (tp + fn) : 1.0
  return p + r === 0 ? 0.0 : (2 * p * r) / (p + r)
}

export function amountOk(a: unknown, b: unknown, tol = 1): boolean {
  const x = pyInt(a)
  const y = pyInt(b)
  return x !== null && y !== null && Math.abs(x - y) <= tol
}
