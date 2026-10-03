// Item-by-item comparison of a submission against golden (powers «Comparar con golden»).
// Each ItemScore lists only the differences the scorer penalises, so `exact` ⇔ full credit.

import type { Deliverables, FieldDiff, ItemId, ItemScore } from '@/domain/types'
import { apItemId, arBillingItemId, arCashItemId, bankAccountItemId, bankItemId, bankRowKeys, closeItemId, icItemId } from '../ids'
import { f1, jeMatchDetail } from './primitives'
import { get, getOr, pyEq, pyIter, truthy, tupleKey, type Counter } from './py'
import {
  apCoding,
  apHeaderChecks,
  apPayeeOk,
  apPo,
  apReasonsOk,
  arBillingHeaderChecks,
  arBillingItemScore,
  arCashParts,
  bankAccountParts,
  closeHit,
  closeKeyParts,
  closeTotals,
  icKey,
  type Rows,
} from './tasks'

type PerItem = Record<ItemId, ItemScore>

const missingItem = (item: ItemId, key: unknown, score: number | null): ItemScore => ({
  item,
  score,
  exact: false,
  diffs: [{ path: 'item', expected: key, actual: null }],
})

const extraItem = (item: ItemId, key: unknown): ItemScore => ({
  item,
  score: null,
  exact: false,
  diffs: [{ path: 'item', expected: null, actual: key }],
})

const finish = (item: ItemId, score: number | null, diffs: FieldDiff[]): ItemScore => ({ item, score, exact: diffs.length === 0, diffs })

function jeDiff(path: string, gold: unknown, sub: unknown, company: unknown): { score: number; diff: FieldDiff | null } {
  const d = jeMatchDetail(gold, sub, company)
  const diff = d.missing.length || d.extra.length ? { path, expected: d.missing, actual: d.extra } : null
  return { score: d.score, diff }
}

function indexBy(rows: Rows, key: string): Map<unknown, unknown> {
  const m = new Map<unknown, unknown>()
  for (const r of rows) m.set(get(r, key), r)
  return m
}

// ---------------------------------------------------------------- AP
function apItems(gold: Rows, sub: Rows, out: PerItem) {
  const S = indexBy(sub, 'doc_id')
  const goldIds = new Set(gold.map((g) => get(g, 'doc_id')))
  for (const g of gold) {
    const key = get(g, 'doc_id')
    const id = apItemId(key)
    const s = S.get(key) ?? {}
    const gd = get(g, 'decision')
    const parts: [number, number][] = [[0.3, pyEq(get(s, 'decision'), gd) ? 1 : 0]]
    const diffs: FieldDiff[] = []
    if (!pyEq(get(s, 'decision'), gd)) diffs.push({ path: 'decision', expected: gd, actual: get(s, 'decision') })
    const r = apReasonsOk(g, s)
    if (r !== null) {
      parts.push([0.05, r])
      if (!r) {
        if (gd === 'DUPLICATE') diffs.push({ path: 'duplicate_of', expected: get(g, 'duplicate_of'), actual: get(s, 'duplicate_of') })
        else diffs.push({ path: 'reasons', expected: get(g, 'reasons'), actual: get(s, 'reasons') })
      }
    }
    if (gd === 'POST' || gd === 'POST_PAYMENT_BLOCK') {
      const checks = apHeaderChecks(g, s)
      const ok = Object.values(checks)
      parts.push([0.15, ok.filter(Boolean).length / ok.length])
      for (const [field, good] of Object.entries(checks)) {
        if (good) continue
        diffs.push({ path: `header.${field}`, expected: get(g, field), actual: get(s, field) })
      }
      const coding = apCoding(g, s)
      parts.push([0.15, coding.score])
      for (const u of coding.uncovered) {
        diffs.push({
          path: 'lines.coding',
          expected: pick(u.line, ['account', 'cost_center', 'wbs', 'tax_code', 'amount']),
          actual: { covered: u.covered },
        })
      }
      const po = apPo(g, s)
      if (po) {
        parts.push([0.1, po.score])
        for (const l of po.missing) diffs.push({ path: 'lines.po', expected: pick(l, ['po', 'po_item', 'amount']), actual: null })
      }
      if (truthy(get(g, 'journal_entry'))) {
        const je = jeDiff('journal_entry.lines', get(g, 'journal_entry'), get(s, 'journal_entry'), get(g, 'company'))
        parts.push([0.2, je.score])
        if (je.diff) diffs.push(je.diff)
      }
      const pb = apPayeeOk(g, s)
      if (pb !== null) {
        parts.push([0.05, pb])
        if (!pb) {
          diffs.push({ path: 'payee', expected: get(g, 'payee'), actual: get(s, 'payee') })
          if (truthy(get(g, 'payment_block'))) diffs.push({ path: 'payment_block', expected: get(g, 'payment_block'), actual: get(s, 'payment_block') })
        }
      }
    }
    const score = weighted(parts)
    out[id] = S.has(key) ? finish(id, score, diffs) : missingItem(id, key, score)
  }
  for (const [key] of S) if (!goldIds.has(key)) out[apItemId(key)] = extraItem(apItemId(key), key)
}

const weighted = (parts: [number, number][]): number => {
  const w = parts.reduce((s, [x]) => s + x, 0)
  return parts.reduce((s, [x, v]) => s + x * v, 0) / w
}

function pick(o: unknown, keys: string[]): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const k of keys) out[k] = get(o, k)
  return out
}

// ---------------------------------------------------------------- AR billing
function arBillingItems(gold: Rows, sub: Rows, out: PerItem) {
  const S = indexBy(sub, 'billing_item')
  const goldIds = new Set(gold.map((g) => get(g, 'billing_item')))
  for (const g of gold) {
    const key = get(g, 'billing_item')
    const id = arBillingItemId(key)
    const s = S.get(key) ?? {}
    const score = arBillingItemScore(g, s)
    const diffs: FieldDiff[] = []
    if (!pyEq(get(s, 'expected'), get(g, 'expected'))) diffs.push({ path: 'expected', expected: get(g, 'expected'), actual: get(s, 'expected') })
    else if (get(g, 'expected') === 'INVOICE') {
      const gi = get(g, 'invoice')
      const si = get(s, 'invoice')
      for (const [field, good] of Object.entries(arBillingHeaderChecks(g, s))) {
        if (!good) diffs.push({ path: `invoice.${field}`, expected: get(gi, field), actual: get(si, field) })
      }
      const je = jeDiff('journal_entry.lines', get(g, 'journal_entry'), get(s, 'journal_entry'), get(g, 'company'))
      if (je.diff) diffs.push(je.diff)
    }
    out[id] = S.has(key) ? finish(id, score, diffs) : missingItem(id, key, score)
  }
  for (const [key] of S) if (!goldIds.has(key)) out[arBillingItemId(key)] = extraItem(arBillingItemId(key), key)
}

// ---------------------------------------------------------------- AR cash
function counterDiff(path: string, g: Counter, s: Counter, labels: [string, string]): FieldDiff | null {
  const decode = (k: string, n: number) => {
    const [a, b] = JSON.parse(k) as unknown[]
    return Array.from({ length: n }, () => ({ [labels[0]]: a, [labels[1]]: b }))
  }
  const missing = [...g].flatMap(([k, n]) => decode(k, n - Math.min(n, s.get(k) ?? 0)))
  const extra = [...s].flatMap(([k, n]) => decode(k, n - Math.min(n, g.get(k) ?? 0)))
  return missing.length || extra.length ? { path, expected: missing, actual: extra } : null
}

function arCashItems(gold: Rows, sub: Rows, out: PerItem) {
  const S = indexBy(sub, 'bank_line')
  const goldIds = new Set(gold.map((g) => get(g, 'bank_line')))
  for (const g of gold) {
    const key = get(g, 'bank_line')
    const id = arCashItemId(key)
    const s = S.get(key) ?? {}
    const p = arCashParts(g, s)
    const diffs: FieldDiff[] = []
    if (!p.cust) diffs.push({ path: 'customer', expected: get(g, 'customer'), actual: get(s, 'customer') })
    const app = counterDiff('applications', p.ga, p.sa, ['ref', 'amount'])
    if (app) diffs.push(app)
    const res = counterDiff('residuals', p.gr, p.sr, ['type', 'amount'])
    if (res) diffs.push(res)
    const je = jeDiff('adjustment', get(g, 'adjustment'), truthy(get(s, 'adjustment')) ? get(s, 'adjustment') : [], get(g, 'company'))
    if (je.diff) diffs.push(je.diff)
    out[id] = S.has(key) ? finish(id, p.score, diffs) : missingItem(id, key, p.score)
  }
  for (const [key] of S) if (!goldIds.has(key)) out[arCashItemId(key)] = extraItem(arCashItemId(key), key)
}

// ---------------------------------------------------------------- bank reconciliation
const decodePair = (k: string) => {
  const [bank_line, book_line] = JSON.parse(k) as unknown[]
  return { bank_line, book_line }
}

function bankItems(gold: Rows, sub: Rows, out: PerItem) {
  const S = indexBy(sub, 'account')
  const goldAccounts = new Set(gold.map((g) => get(g, 'account')))
  for (const g of gold) {
    const account = get(g, 'account')
    const s = S.get(account) ?? {}
    const p = bankAccountParts(g, s)
    const keys = bankRowKeys(g)
    const goldIds = new Set<ItemId>()
    // Gold matches: their pairs, plus submitted pairs that touch the same lines.
    pyIter(get(g, 'matches')).forEach((m, i) => {
      const id = bankItemId(account, keys.matches[i])
      goldIds.add(id)
      const banks = new Set(pyIter(get(m, 'bank_lines')).map((x) => tupleKey(x)))
      const books = new Set(pyIter(get(m, 'book_lines')).map((x) => tupleKey(x)))
      const own = [...p.gp].filter((k) => {
        const [b, l] = JSON.parse(k) as unknown[]
        return banks.has(tupleKey(b)) && books.has(tupleKey(l))
      })
      const touching = [...p.sp].filter((k) => {
        const [b, l] = JSON.parse(k) as unknown[]
        return banks.has(tupleKey(b)) || books.has(tupleKey(l))
      })
      const missing = own.filter((k) => !p.sp.has(k))
      const extra = touching.filter((k) => !p.gp.has(k))
      const diffs: FieldDiff[] = []
      if (missing.length || extra.length) diffs.push({ path: 'matches', expected: missing.map(decodePair), actual: extra.map(decodePair) })
      const score = f1(own.length - missing.length, extra.length, missing.length)
      out[id] = finish(id, score, diffs)
    })
    // Gold unmatched lines: found on the same side and with the same category.
    const unmatched = [
      ...pyIter(get(g, 'unmatched_bank')).map((x, i) => ({ side: 'B', line: get(x, 'bank_line'), cat: get(x, 'category'), key: keys.unmatchedBank[i] })),
      ...pyIter(get(g, 'unmatched_book')).map((x, i) => ({ side: 'L', line: get(x, 'book_line'), cat: get(x, 'category'), key: keys.unmatchedBook[i] })),
    ]
    for (const u of unmatched) {
      const id = bankItemId(account, u.key)
      goldIds.add(id)
      const k = tupleKey(u.side, u.line)
      const found = p.su.has(k)
      const catOk = pyEq(p.su.get(k) ?? null, u.cat)
      const path = u.side === 'B' ? 'unmatched_bank' : 'unmatched_book'
      const diffs: FieldDiff[] = []
      if (!found) {
        const matched = [...p.sp].filter((x) => tupleKey((JSON.parse(x) as unknown[])[u.side === 'B' ? 0 : 1]) === tupleKey(u.line))
        diffs.push({ path, expected: u.cat, actual: matched.length ? { matches: matched.map(decodePair) } : null })
      } else if (!catOk) diffs.push({ path: `${path}.category`, expected: u.cat, actual: p.su.get(k) })
      out[id] = finish(id, found ? (catOk ? 1 : 0.5) : 0, diffs)
    }
    // Submitted lines/matches the gold does not have.
    const sKeys = bankRowKeys(s)
    pyIter(getOr(s, 'matches', [])).forEach((m, i) => {
      const extra: string[] = []
      for (const b of pyIter(getOr(m, 'bank_lines', []))) {
        for (const l of pyIter(getOr(m, 'book_lines', []))) if (!p.gp.has(tupleKey(b, l))) extra.push(tupleKey(b, l))
      }
      const id = bankItemId(account, sKeys.matches[i])
      if (extra.length && !goldIds.has(id)) out[id] = { ...extraItem(id, sKeys.matches[i]), diffs: [{ path: 'matches', expected: null, actual: extra.map(decodePair) }] }
    })
    const subUnmatched = [
      ...pyIter(getOr(s, 'unmatched_bank', [])).map((x, i) => ({ side: 'B', line: get(x, 'bank_line'), cat: get(x, 'category'), key: sKeys.unmatchedBank[i] })),
      ...pyIter(getOr(s, 'unmatched_book', [])).map((x, i) => ({ side: 'L', line: get(x, 'book_line'), cat: get(x, 'category'), key: sKeys.unmatchedBook[i] })),
    ]
    for (const u of subUnmatched) {
      if (p.gu.has(tupleKey(u.side, u.line))) continue
      const path = u.side === 'B' ? 'unmatched_bank' : 'unmatched_book'
      const id = bankItemId(account, String(u.line))
      const existing = out[id]
      if (existing && goldIds.has(id)) {
        existing.diffs.push({ path, expected: null, actual: u.cat })
        existing.exact = false
      } else out[bankItemId(account, u.key)] = { ...extraItem(bankItemId(account, u.key), u.line), diffs: [{ path, expected: null, actual: u.cat }] }
    }
    // Account level: adjustments and the account score.
    const accId = bankAccountItemId(account)
    const je = jeDiff('adjustments', pyIter(get(g, 'adjustments')).flatMap((a) => pyIter(get(a, 'lines'))), pyIter(getOr(s, 'adjustments', [])).flatMap((a) => pyIter(getOr(a, 'lines', []))), get(g, 'company'))
    const accDiffs: FieldDiff[] = je.diff ? [je.diff] : []
    out[accId] = S.has(account) ? finish(accId, p.score, accDiffs) : missingItem(accId, account, p.score)
  }
  for (const [account] of S) if (!goldAccounts.has(account)) out[bankAccountItemId(account)] = extraItem(bankAccountItemId(account), account)
}

// ---------------------------------------------------------------- intercompany
function icItems(gold: Rows, sub: Rows, out: PerItem) {
  const sk = new Map<string, unknown>()
  for (const s of sub) sk.set(icKey(s, false), s)
  const gk = new Map<string, unknown>()
  for (const g of gold) gk.set(icKey(g, true), g)
  for (const [k, g] of gk) {
    const id = icItemId(get(g, 'pair'), get(g, 'cause'))
    const s = sk.get(k)
    if (!truthy(s)) {
      out[id] = missingItem(id, { pair: get(g, 'pair'), cause: get(g, 'cause') }, 0)
      continue
    }
    const je = jeDiff('adjustment', get(g, 'adjustment'), truthy(get(s, 'adjustment')) ? get(s, 'adjustment') : [], null)
    out[id] = finish(id, 0.6 + 0.4 * je.score, je.diff ? [je.diff] : [])
  }
  for (const [k, s] of sk) {
    if (gk.has(k)) continue
    const id = icItemId(getOr(s, 'pair', []), get(s, 'cause'))
    out[id] = extraItem(id, { pair: get(s, 'pair'), cause: get(s, 'cause') })
  }
}

// ---------------------------------------------------------------- close
function closeItems(gold: Rows, sub: Rows, out: PerItem) {
  const G = closeTotals(gold)
  const Sx = closeTotals(sub)
  for (const [k, v] of G) {
    const id = closeItemId(...closeKeyParts(v.row))
    const s = Sx.get(k)
    if (!s) {
      out[id] = missingItem(id, JSON.parse(k), 0)
      continue
    }
    const hit = closeHit(v.type, v.total, s.total)
    out[id] = finish(id, hit, hit === 1 ? [] : [{ path: 'amount', expected: v.total, actual: s.total }])
  }
  for (const [k, v] of Sx) {
    if (G.has(k)) continue
    const id = closeItemId(...closeKeyParts(v.row))
    out[id] = extraItem(id, JSON.parse(k))
  }
}

/** Per-item comparison of a submission (absent files = empty) against the golden deliverables. */
export function diffItems(gold: Deliverables, sub: Deliverables): Record<ItemId, ItemScore> {
  const out: PerItem = {}
  apItems(gold.ap, sub.ap, out)
  arBillingItems(gold.ar_billing, sub.ar_billing, out)
  arCashItems(gold.ar_cash, sub.ar_cash, out)
  bankItems(gold.bank_rec, sub.bank_rec, out)
  icItems(gold.ic, sub.ic, out)
  closeItems(gold.close, sub.close, out)
  return out
}

