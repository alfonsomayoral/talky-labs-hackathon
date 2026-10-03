// Python semantics needed to port score.py bit for bit: dict.get, truthiness,
// int(), ==, hashable tuple keys, Counter, float sum (Neumaier, CPython ≥ 3.12) and round().

export type PyDict = Record<string, unknown>

export const isDict = (x: unknown): x is PyDict => typeof x === 'object' && x !== null && !Array.isArray(x)

/** `d.get(k)`: a missing key and JSON null both read as None (null). Non-dicts read as {}. */
export function get(o: unknown, k: string): unknown {
  if (!isDict(o)) return null
  const v = o[k]
  return v === undefined ? null : v
}

/** `d.get(k, default)`: the default only applies when the key is absent. */
export function getOr(o: unknown, k: string, dflt: unknown): unknown {
  if (!isDict(o) || !(k in o) || o[k] === undefined) return dflt
  return o[k]
}

export function truthy(x: unknown): boolean {
  if (x === null || x === undefined || x === false || x === 0 || x === '') return false
  if (Array.isArray(x)) return x.length > 0
  if (isDict(x)) return Object.keys(x).length > 0
  return true
}

/** `a or b or c`: first truthy operand, else the last one. */
export function or(...xs: unknown[]): unknown {
  for (const x of xs) if (truthy(x)) return x
  return xs.length ? (xs[xs.length - 1] ?? null) : null
}

/** `int(x)`; null where Python would raise. */
export function pyInt(x: unknown): number | null {
  if (typeof x === 'boolean') return x ? 1 : 0
  if (typeof x === 'number') return Number.isFinite(x) ? Math.trunc(x) : null
  if (typeof x === 'string') {
    const s = x.trim()
    return /^[+-]?\d+(_\d+)*$/.test(s) ? Number(s.replace(/_/g, '')) : null
  }
  return null
}

/** `int(x or 0)`. Python raises on garbage; here it counts as 0. */
export const intOr0 = (x: unknown): number => (truthy(x) ? (pyInt(x) ?? 0) : 0)

/** `str(x)` for the scalars that appear in account fields. */
export function pyStr(x: unknown): string {
  if (x === null || x === undefined) return 'None'
  if (typeof x === 'boolean') return x ? 'True' : 'False'
  if (typeof x === 'string') return x
  if (typeof x === 'number') return String(x)
  return JSON.stringify(x)
}

/** `a == b` for JSON values (bool == int like Python, deep for lists and dicts). */
export function pyEq(a: unknown, b: unknown): boolean {
  const x = a ?? null
  const y = b ?? null
  if (typeof x === 'boolean' && typeof y === 'number') return (x ? 1 : 0) === y
  if (typeof y === 'boolean' && typeof x === 'number') return (y ? 1 : 0) === x
  if (x === null || y === null || typeof x !== 'object' || typeof y !== 'object') return x === y
  if (Array.isArray(x) || Array.isArray(y)) {
    if (!Array.isArray(x) || !Array.isArray(y) || x.length !== y.length) return false
    return x.every((v, i) => pyEq(v, y[i]))
  }
  const kx = Object.keys(x)
  const dy = y as PyDict
  return kx.length === Object.keys(dy).length && kx.every((k) => k in dy && pyEq((x as PyDict)[k], dy[k]))
}

/** Hashable tuple key: None and missing collapse, "1" ≠ 1 like Python. */
export const tupleKey = (...parts: unknown[]): string => JSON.stringify(parts.map((p) => p ?? null))

/** Iterates like Python `for x in v` over JSON values (list items, str chars, dict keys). */
export function pyIter(v: unknown): unknown[] {
  if (Array.isArray(v)) return v
  if (typeof v === 'string') return [...v]
  if (isDict(v)) return Object.keys(v)
  return []
}

/** `sorted()` ordering for the scalars that appear in keys. */
export function pyCompare(a: unknown, b: unknown): number {
  if (typeof a === 'number' && typeof b === 'number') return a - b
  const sa = typeof a === 'string' ? a : JSON.stringify(a ?? null)
  const sb = typeof b === 'string' ? b : JSON.stringify(b ?? null)
  return sa < sb ? -1 : sa > sb ? 1 : 0
}

// ---------------------------------------------------------------- Counter
export type Counter = Map<string, number>

export function counter(keys: Iterable<string>): Counter {
  const c: Counter = new Map()
  for (const k of keys) c.set(k, (c.get(k) ?? 0) + 1)
  return c
}

export function counterEq(a: Counter, b: Counter): boolean {
  if (a.size !== b.size) return false
  for (const [k, v] of a) if (b.get(k) !== v) return false
  return true
}

export const counterTotal = (c: Counter): number => [...c.values()].reduce((s, v) => s + v, 0)

/** `sum((a & b).values())`. */
export function counterAndTotal(a: Counter, b: Counter): number {
  let n = 0
  for (const [k, v] of a) n += Math.min(v, b.get(k) ?? 0)
  return n
}

// ---------------------------------------------------------------- floats
/** `sum(xs)` of Python floats: Neumaier compensated summation (CPython ≥ 3.12). */
export function fsum(xs: readonly number[]): number {
  if (xs.length === 0) return 0
  let hi = 0 + xs[0]
  let lo = 0
  for (let i = 1; i < xs.length; i++) {
    const x = xs[i]
    const t = hi + x
    if (Math.abs(hi) >= Math.abs(x)) lo += hi - t + x
    else lo += x - t + hi
    hi = t
  }
  return lo && Number.isFinite(lo) ? hi + lo : hi
}

/** `sum(xs)` of Python ints (exact below 2^53). */
export const isum = (xs: readonly number[]): number => xs.reduce((s, x) => s + x, 0)

/** `round(x, n)`: correctly rounded, ties to even on the exact binary value. */
export function pyRound(x: number, n: number): number {
  if (!Number.isFinite(x)) return x
  const neg = x < 0
  // Exact decimal expansion (ES2018 allows 100 digits; every double in [1e-5, 1e21) fits).
  // oxlint-disable-next-line oxc/number-arg-out-of-range
  const [ip, fp] = Math.abs(x).toFixed(100).split('.')
  const rest = fp.slice(n)
  let digits = ip + fp.slice(0, n)
  const up = rest[0] > '5' || (rest[0] === '5' && (/[1-9]/.test(rest.slice(1)) || Number(digits[digits.length - 1]) % 2 === 1))
  if (up) {
    const d = digits.split('')
    let i = d.length - 1
    for (; i >= 0; i--) {
      if (d[i] === '9') d[i] = '0'
      else {
        d[i] = String(Number(d[i]) + 1)
        break
      }
    }
    if (i < 0) d.unshift('1')
    digits = d.join('')
  }
  const r = n > 0 ? Number(`${digits.slice(0, digits.length - n)}.${digits.slice(digits.length - n)}`) : Number(digits)
  return neg ? -r : r
}
