// Per-task scorers: line-by-line port of score.py (score_ap … score_tb).

import type { TaskKey, TrialBalanceRow } from '@/domain/types'
import { TASK_KEYS } from '@/domain/types'
import { rowEntries } from '../ledger/entries'
import { amountOk, f1, jeLines, jeMatch, normNum } from './primitives'
import {
  counter,
  counterAndTotal,
  counterEq,
  counterTotal,
  fsum,
  get,
  getOr,
  intOr0,
  isum,
  pyCompare,
  pyEq,
  pyIter,
  pyRound,
  truthy,
  tupleKey,
} from './py'

export type Rows = readonly unknown[]
export interface TaskResult {
  score: number
  details: Record<string, unknown>
}

const avg = (x: number[]): number => (x.length ? fsum(x) / x.length : 1.0)

/** `{s[key]: s for s in sub}` — the last row wins. */
function indexBy(rows: Rows, key: string): Map<unknown, unknown> {
  const m = new Map<unknown, unknown>()
  for (const r of rows) m.set(get(r, key), r)
  return m
}

// ---------------------------------------------------------------------- AP
export const AP_COMPONENT_WEIGHTS = {
  decision_macro_f1: 0.3,
  header: 0.15,
  coding: 0.15,
  po_match: 0.1,
  journal_entry: 0.2,
  reasons: 0.05,
  payee_and_block: 0.05,
} as const

/** AP header checks of one posted document (fraction of fields right). */
export function apHeaderChecks(g: unknown, s: unknown): Record<string, boolean> {
  const out: Record<string, boolean> = {
    company: pyEq(get(s, 'company'), get(g, 'company')),
    vendor_id: pyEq(get(s, 'vendor_id'), get(g, 'vendor_id')),
    invoice_number: normNum(get(s, 'invoice_number')) === normNum(get(g, 'invoice_number')),
    invoice_date: pyEq(get(s, 'invoice_date'), get(g, 'invoice_date')),
  }
  for (const k of ['net', 'tax', 'gross', 'withholding', 'retention', 'payable']) out[k] = amountOk(get(s, k), get(g, k))
  return out
}

interface CodingKeyed {
  key: string
  amount: number
}

/** Amount-weighted line coding on (account, cost_center, wbs, tax_code). */
export function apCoding(g: unknown, s: unknown): { score: number; uncovered: { line: unknown; covered: number }[] } {
  const gLines = pyIter(getOr(g, 'lines', []))
  const gl: (CodingKeyed & { line: unknown })[] = gLines.map((l) => ({
    key: tupleKey(get(l, 'account'), get(l, 'cost_center'), get(l, 'wbs'), get(l, 'tax_code')),
    amount: get(l, 'amount') as number,
    line: l,
  }))
  const samt = new Map<string, number>()
  for (const l of pyIter(getOr(s, 'lines', []))) {
    const k = tupleKey(get(l, 'account'), get(l, 'cost_center'), get(l, 'wbs'), get(l, 'tax_code'))
    samt.set(k, (samt.get(k) ?? 0) + intOr0(get(l, 'amount')))
  }
  const tot = isum(gl.map((x) => Math.abs(x.amount))) || 1
  let ok = 0
  const uncovered: { line: unknown; covered: number }[] = []
  for (const x of gl) {
    const take = Math.min(Math.abs(x.amount), Math.abs(samt.get(x.key) ?? 0))
    ok += take
    if (samt.has(x.key)) {
      const cur = samt.get(x.key) as number
      samt.set(x.key, cur > 0 ? cur - take : cur + take)
    }
    if (take < Math.abs(x.amount)) uncovered.push({ line: x.line, covered: take })
  }
  return { score: ok / tot, uncovered }
}

/** Share (by amount) of gold PO lines whose (po, po_item) appears in the submission; null when no PO lines. */
export function apPo(g: unknown, s: unknown): { score: number; missing: unknown[] } | null {
  const gp = pyIter(getOr(g, 'lines', [])).filter((l) => truthy(get(l, 'po')))
  if (!gp.length) return null
  const sp = counter(
    pyIter(getOr(s, 'lines', []))
      .filter((l) => truthy(get(l, 'po')))
      .map((l) => tupleKey(get(l, 'po'), get(l, 'po_item'))),
  )
  const missing: unknown[] = []
  let good = 0
  for (const l of gp) {
    if (sp.get(tupleKey(get(l, 'po'), get(l, 'po_item')))) good += Math.abs(get(l, 'amount') as number)
    else missing.push(l)
  }
  const total = isum(gp.map((l) => Math.abs(get(l, 'amount') as number))) || 1
  return { score: good / total, missing }
}

const or0 = (x: unknown): unknown => (truthy(x) ? x : [])

export function apReasonsOk(g: unknown, s: unknown): number | null {
  const gd = get(g, 'decision')
  if ((gd === 'HOLD' || gd === 'REJECT' || gd === 'POST_PAYMENT_BLOCK') && truthy(get(g, 'reasons'))) {
    const sub = new Set(pyIter(or0(get(s, 'reasons'))).map((x) => tupleKey(x)))
    return pyIter(get(g, 'reasons')).some((x) => sub.has(tupleKey(x))) ? 1.0 : 0.0
  }
  if (gd === 'DUPLICATE') return pyEq(get(s, 'duplicate_of'), get(g, 'duplicate_of')) ? 1.0 : 0.0
  return null
}


export function apPayeeOk(g: unknown, s: unknown): number | null {
  const gp = get(g, 'payee')
  const gb = get(g, 'payment_block')
  if (!truthy(gp) && !truthy(gb)) return null
  const okP = truthy(gp) ? pyEq(get(truthy(get(s, 'payee')) ? get(s, 'payee') : {}, 'type'), get(gp, 'type')) : true
  const okB = truthy(gb) ? pyEq(get(s, 'payment_block'), gb) : true
  return okP && okB ? 1.0 : 0.0
}

export function scoreAp(gold: Rows, sub: Rows): TaskResult {
  const S = indexBy(sub, 'doc_id')
  const classSet = new Set<unknown>()
  for (const g of gold) classSet.add(get(g, 'decision'))
  for (const s of sub) if (truthy(get(s, 'decision'))) classSet.add(get(s, 'decision'))
  const classes = [...classSet].sort(pyCompare)
  const tp = new Map<unknown, number>()
  const fp = new Map<unknown, number>()
  const fn = new Map<unknown, number>()
  const inc = (m: Map<unknown, number>, k: unknown) => m.set(k, (m.get(k) ?? 0) + 1)
  const header: number[] = []
  const coding: number[] = []
  const po: number[] = []
  const je: number[] = []
  const reasons: number[] = []
  const payee: number[] = []
  for (const g of gold) {
    const s = S.get(get(g, 'doc_id')) ?? {}
    const gd = get(g, 'decision')
    const sd = get(s, 'decision')
    if (pyEq(sd, gd)) inc(tp, gd)
    else {
      inc(fn, gd)
      if (truthy(sd)) inc(fp, sd)
    }
    const r = apReasonsOk(g, s)
    if (r !== null) reasons.push(r)
    if (gd !== 'POST' && gd !== 'POST_PAYMENT_BLOCK') continue
    const fields = Object.values(apHeaderChecks(g, s))
    header.push(isum(fields.map(Number)) / fields.length)
    coding.push(apCoding(g, s).score)
    const p = apPo(g, s)
    if (p) po.push(p.score)
    if (truthy(get(g, 'journal_entry'))) je.push(jeMatch(get(g, 'journal_entry'), get(s, 'journal_entry'), get(g, 'company')))
    const pb = apPayeeOk(g, s)
    if (pb !== null) payee.push(pb)
  }
  const f1Of = (c: unknown) => f1(tp.get(c) ?? 0, fp.get(c) ?? 0, fn.get(c) ?? 0)
  const macro = fsum(classes.map(f1Of)) / Math.max(1, classes.length)
  const parts = {
    decision_macro_f1: macro,
    header: avg(header),
    coding: avg(coding),
    po_match: avg(po),
    journal_entry: avg(je),
    reasons: avg(reasons),
    payee_and_block: avg(payee),
  }
  const total =
    0.3 * macro +
    0.15 * parts.header +
    0.15 * parts.coding +
    0.1 * parts.po_match +
    0.2 * parts.journal_entry +
    0.05 * parts.reasons +
    0.05 * parts.payee_and_block
  const perClass: Record<string, number> = {}
  for (const c of classes) perClass[String(c)] = pyRound(f1Of(c), 3)
  return {
    score: total,
    details: { ...parts, per_decision_f1: perClass, documents: gold.length, answered: gold.filter((g) => S.has(get(g, 'doc_id'))).length },
  }
}

// ---------------------------------------------------------------------- AR billing
export function arBillingHeaderChecks(g: unknown, s: unknown): Record<string, boolean> {
  const gi = get(g, 'invoice')
  const si = truthy(get(s, 'invoice')) ? get(s, 'invoice') : {}
  const out: Record<string, boolean> = {
    tax_code: pyEq(get(si, 'tax_code'), get(gi, 'tax_code')),
    due_date: pyEq(get(si, 'due_date'), get(gi, 'due_date')),
  }
  for (const k of ['net', 'tax', 'retention', 'payable']) out[k] = amountOk(get(si, k), get(gi, k))
  if (truthy(get(gi, 'face'))) {
    const sf = truthy(get(si, 'face')) ? get(si, 'face') : {}
    out.face = ['oficina_contable', 'organo_gestor', 'unidad_tramitadora'].every((k) => pyEq(get(sf, k), get(get(gi, 'face'), k)))
  }
  return out
}

/** Score of one billing item (0 when `expected` differs). */
export function arBillingItemScore(g: unknown, s: unknown): number {
  if (!pyEq(get(s, 'expected'), get(g, 'expected'))) return 0.0
  if (get(g, 'expected') !== 'INVOICE') return 1.0
  const checks = Object.values(arBillingHeaderChecks(g, s))
  const head = isum(checks.map(Number)) / checks.length
  return 0.6 * head + 0.4 * jeMatch(get(g, 'journal_entry'), get(s, 'journal_entry'), get(g, 'company'))
}

export function scoreArBilling(gold: Rows, sub: Rows): TaskResult {
  const S = indexBy(sub, 'billing_item')
  const scores = gold.map((g) => arBillingItemScore(g, S.get(get(g, 'billing_item')) ?? {}))
  return {
    score: scores.length ? fsum(scores) / scores.length : 1.0,
    details: { items: gold.length, answered: gold.filter((g) => S.has(get(g, 'billing_item'))).length },
  }
}

// ---------------------------------------------------------------------- AR cash application
export const appKey = (a: unknown, amount: unknown): string => tupleKey(truthy(get(a, 'invoice')) ? get(a, 'invoice') : get(a, 'pagare'), amount)

export function arCashParts(g: unknown, s: unknown) {
  const ga = counter(pyIter(get(g, 'applications')).map((a) => appKey(a, get(a, 'amount'))))
  const sa = counter(pyIter(getOr(s, 'applications', [])).map((a) => appKey(a, intOr0(get(a, 'amount')))))
  const multisetScore = (x: ReturnType<typeof counter>, y: ReturnType<typeof counter>) =>
    counterEq(x, y) ? 1.0 : x.size || y.size ? counterAndTotal(x, y) / Math.max(counterTotal(x), counterTotal(y)) : 1.0
  const app = multisetScore(ga, sa)
  const gr = counter(pyIter(get(g, 'residuals')).map((r) => tupleKey(get(r, 'type'), get(r, 'amount'))))
  const sr = counter(pyIter(getOr(s, 'residuals', [])).map((r) => tupleKey(get(r, 'type'), intOr0(get(r, 'amount')))))
  const res = multisetScore(gr, sr)
  const cust = pyEq(get(s, 'customer'), get(g, 'customer')) ? 1.0 : 0.0
  const adj = jeMatch(get(g, 'adjustment'), truthy(get(s, 'adjustment')) ? get(s, 'adjustment') : [], get(g, 'company'))
  const score = 0.15 * cust + 0.45 * app + 0.2 * res + 0.2 * adj
  return { ga, sa, gr, sr, app, res, cust, adj, score }
}

export function scoreArCash(gold: Rows, sub: Rows): TaskResult {
  const S = indexBy(sub, 'bank_line')
  const scores: number[] = []
  let exact = 0
  for (const g of gold) {
    const sc = arCashParts(g, S.get(get(g, 'bank_line')) ?? {}).score
    if (sc === 1.0) exact += 1
    scores.push(sc)
  }
  return { score: scores.length ? fsum(scores) / scores.length : 1.0, details: { receipts: gold.length, fully_correct: exact } }
}

// ---------------------------------------------------------------------- bank reconciliation
export const pairKey = (b: unknown, k: unknown): string => tupleKey(b, k)

export function bankPairs(row: unknown, strict: boolean): Set<string> {
  const out = new Set<string>()
  const matches = strict ? pyIter(get(row, 'matches')) : pyIter(getOr(row, 'matches', []))
  for (const m of matches) {
    const banks = strict ? pyIter(get(m, 'bank_lines')) : pyIter(getOr(m, 'bank_lines', []))
    const books = strict ? pyIter(get(m, 'book_lines')) : pyIter(getOr(m, 'book_lines', []))
    for (const b of banks) for (const k of books) out.add(pairKey(b, k))
  }
  return out
}

/** `{("B", bank_line): category} | {("L", book_line): category}`. */
export function bankUnmatched(row: unknown, strict: boolean): Map<string, unknown> {
  const out = new Map<string, unknown>()
  const ub = strict ? pyIter(get(row, 'unmatched_bank')) : pyIter(getOr(row, 'unmatched_bank', []))
  const ul = strict ? pyIter(get(row, 'unmatched_book')) : pyIter(getOr(row, 'unmatched_book', []))
  for (const x of ub) out.set(tupleKey('B', get(x, 'bank_line')), get(x, 'category'))
  for (const x of ul) out.set(tupleKey('L', get(x, 'book_line')), get(x, 'category'))
  return out
}

export function bankAdjustmentLines(row: unknown, strict: boolean): unknown[] {
  const adjs = strict ? pyIter(get(row, 'adjustments')) : pyIter(getOr(row, 'adjustments', []))
  return adjs.flatMap((a) => pyIter(strict ? get(a, 'lines') : getOr(a, 'lines', [])))
}

export function bankAccountParts(g: unknown, s: unknown) {
  const gp = bankPairs(g, true)
  const sp = bankPairs(s, false)
  let inter = 0
  for (const p of gp) if (sp.has(p)) inter++
  const mf = f1(inter, sp.size - inter, gp.size - inter)
  const gu = bankUnmatched(g, true)
  const su = bankUnmatched(s, false)
  let found = 0
  let cat = 0
  for (const [k, v] of gu) {
    if (su.has(k)) found++
    if (pyEq(su.get(k) ?? null, v)) cat++
  }
  let suOnly = 0
  for (const k of su.keys()) if (!gu.has(k)) suOnly++
  const uf = f1(found, suOnly, gu.size - found)
  const catacc = gu.size ? cat / gu.size : 1.0
  const adj = jeMatch(bankAdjustmentLines(g, true), bankAdjustmentLines(s, false), get(g, 'company'))
  const score = 0.45 * mf + 0.2 * uf + 0.15 * catacc + 0.2 * adj
  return { gp, sp, gu, su, mf, uf, catacc, adj, score }
}

export function scoreBank(gold: Rows, sub: Rows): TaskResult {
  const S = indexBy(sub, 'account')
  const perAccount: Record<string, number> = {}
  const tot: number[] = []
  for (const g of gold) {
    const sc = bankAccountParts(g, S.get(get(g, 'account')) ?? {}).score
    perAccount[String(get(g, 'account'))] = pyRound(sc, 4)
    tot.push(sc)
  }
  return { score: tot.length ? fsum(tot) / tot.length : 1.0, details: { per_account: perAccount } }
}

// ---------------------------------------------------------------------- intercompany
export const icKey = (row: unknown, strict: boolean): string =>
  tupleKey([...pyIter(strict ? get(row, 'pair') : getOr(row, 'pair', []))].sort(pyCompare), get(row, 'cause'))

export function scoreIc(gold: Rows, sub: Rows): TaskResult {
  const gk = new Map<string, unknown>()
  for (const g of gold) gk.set(icKey(g, true), g)
  const sk = new Map<string, unknown>()
  for (const s of sub) sk.set(icKey(s, false), s)
  let tp = 0
  for (const k of gk.keys()) if (sk.has(k)) tp++
  const det = f1(tp, sk.size - tp, gk.size - tp)
  const adj: number[] = []
  for (const [k, g] of gk) {
    const s = sk.get(k)
    adj.push(truthy(s) ? jeMatch(get(g, 'adjustment'), truthy(get(s, 'adjustment')) ? get(s, 'adjustment') : [], null) : 0.0)
  }
  const a = adj.length ? fsum(adj) / adj.length : 1.0
  return { score: 0.6 * det + 0.4 * a, details: { differences: gold.length, detected: tp } }
}

// ---------------------------------------------------------------------- close
const CLOSE_KEY_FIELD: Record<string, string> = {
  ACCRUAL: 'vendor',
  PREPAID: 'invoice',
  FX_REVAL: 'item',
  BAD_DEBT: 'customer',
  WIP_REVENUE: 'billing_item',
}

/** Field that identifies a close row within its type (score.py close_key). */
export const closeKeyField = (type: unknown): string => (typeof type === 'string' && CLOSE_KEY_FIELD[type]) || 'customer'

export const closeKeyParts = (x: unknown): [unknown, unknown, unknown] => {
  const t = get(x, 'type')
  return [t, get(x, 'company'), get(x, closeKeyField(t))]
}

export const closeKey = (x: unknown): string => tupleKey(...closeKeyParts(x))

/** Σamount per close key (DOUBTFUL_RECLASS counts rows), in first-seen order. */
export function closeTotals(rows: Rows): Map<string, { type: unknown; total: number; row: unknown }> {
  const m = new Map<string, { type: unknown; total: number; row: unknown }>()
  for (const r of rows) {
    const k = closeKey(r)
    const add = pyEq(get(r, 'type'), 'DOUBTFUL_RECLASS') ? 1 : intOr0(get(r, 'amount'))
    const cur = m.get(k)
    if (cur) cur.total += add
    else m.set(k, { type: get(r, 'type'), total: add, row: r })
  }
  return m
}

/** 1 within tolerance (±15 % for ACCRUAL, at least 1 €), 0.4 within ±50 %, else 0. */
export function closeHit(type: unknown, gold: number, sub: number): number {
  const tol = type === 'ACCRUAL' ? 0.15 : 0.0
  if (Math.abs(sub - gold) <= Math.max(100, Math.abs(gold) * tol)) return 1
  if (Math.abs(sub - gold) <= Math.abs(gold) * 0.5) return 0.4
  return 0
}

export function scoreClose(gold: Rows, sub: Rows): TaskResult {
  const G = closeTotals(gold)
  const Sx = closeTotals(sub)
  let hits = 0.0
  for (const [k, v] of G) {
    const s = Sx.get(k)
    if (s) hits += closeHit(v.type, v.total, s.total)
  }
  const rec = G.size ? hits / G.size : 1.0
  const prec = Sx.size ? hits / Sx.size : !G.size ? 1.0 : 0.0
  return {
    score: G.size || Sx.size ? f1(hits, Sx.size - hits, G.size - hits) : 1.0,
    details: { items: G.size, recall: pyRound(rec, 3), precision: pyRound(prec, 3) },
  }
}

// ---------------------------------------------------------------------- trial balance
export const tbKey = (company: unknown, account: unknown): string => tupleKey(company, account)

export function tbMap(rows: readonly TrialBalanceRow[]): Map<string, number> {
  const m = new Map<string, number>()
  for (const r of rows) m.set(tbKey(r.company, r.account), r.balance)
  return m
}

export function scoreTb(
  truthRows: readonly TrialBalanceRow[],
  recordedRows: readonly TrialBalanceRow[],
  subs: Record<TaskKey, Rows>,
): TaskResult {
  const truth = tbMap(truthRows)
  const recorded = tbMap(recordedRows)
  const team = new Map(recorded)
  for (const name of TASK_KEYS) {
    for (const r of subs[name]) {
      for (const e of rowEntries(name, r)) {
        for (const l of jeLines(e.je, e.company)) {
          const k = tbKey(l.company, l.account)
          team.set(k, (team.get(k) ?? 0) + l.amount)
        }
      }
    }
  }
  const keys = new Set([...truth.keys(), ...team.keys()])
  let diff = 0
  let base = 0
  for (const k of keys) {
    diff += Math.abs((truth.get(k) ?? 0) - (team.get(k) ?? 0))
    base += Math.abs((truth.get(k) ?? 0) - (recorded.get(k) ?? 0))
  }
  base = base || 1
  return {
    score: Math.max(0.0, 1 - diff / base),
    details: { abs_difference_eur: pyRound(diff / 100, 2), recorded_vs_truth_eur: pyRound(base / 100, 2) },
  }
}

