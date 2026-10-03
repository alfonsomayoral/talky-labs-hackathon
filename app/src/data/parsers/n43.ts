// Norma 43 (AEB Cuaderno 43): fixed 80-char records.
//   11 account header · 22 movement · 23 optional concepts and 24 FX equivalence (belong to
//   the previous 22) · 33 account footer · 88 end of file. Amounts: 14 digits in cents; sign from the D/H key
//   (1 = debe → charge to the account, 2 = haber → credit). Dates YYMMDD.

export interface N43Movement {
  account: string
  office: string
  bookingDate: string
  valueDate: string
  commonConcept: string
  ownConcept: string
  /** Signed cents: positive = credit to the account. */
  amount: number
  documentNumber: string
  reference1: string
  reference2: string
  concepts: string[]
  /** Record 24: original currency and amount (cents) of a foreign-currency movement. */
  fx: { currency: string; amount: number } | null
  /** Records 22 + its 23/24 as they appear in the file. */
  raw: string[]
}

export interface N43Account {
  bank: string
  office: string
  account: string
  from: string
  to: string
  currency: string
  holder: string
  opening: number
  closing: number | null
  debitCount: number | null
  debitTotal: number | null
  creditCount: number | null
  creditTotal: number | null
  movements: N43Movement[]
}

export interface N43File {
  accounts: N43Account[]
  movements: N43Movement[]
  warnings: string[]
}

const CURRENCIES: Record<string, string> = { '978': 'EUR', '840': 'USD', '484': 'MXN', '826': 'GBP' }

export const n43Date = (yymmdd: string) => `20${yymmdd.slice(0, 2)}-${yymmdd.slice(2, 4)}-${yymmdd.slice(4, 6)}`
const cents = (digits: string) => Number(digits)
const signed = (key: string, digits: string) => (key === '1' ? -cents(digits) : cents(digits))

export function parseN43(text: string): N43File {
  const accounts: N43Account[] = []
  const movements: N43Movement[] = []
  const warnings: string[] = []
  let account: N43Account | null = null
  let last: N43Movement | null = null

  const records = text.split('\n')
  for (let i = 0; i < records.length; i++) {
    const rec = records[i].replace(/\r$/, '')
    if (!rec.trim()) continue
    const r = rec.padEnd(80, ' ')
    const code = r.slice(0, 2)
    if (code === '11') {
      account = {
        bank: r.slice(2, 6),
        office: r.slice(6, 10),
        account: r.slice(10, 20),
        from: n43Date(r.slice(20, 26)),
        to: n43Date(r.slice(26, 32)),
        opening: signed(r.slice(32, 33), r.slice(33, 47)),
        currency: CURRENCIES[r.slice(47, 50)] ?? r.slice(47, 50),
        holder: r.slice(51, 77).trim(),
        closing: null,
        debitCount: null,
        debitTotal: null,
        creditCount: null,
        creditTotal: null,
        movements: [],
      }
      accounts.push(account)
      last = null
    } else if (code === '22') {
      if (!account) warnings.push(`Registro 22 sin cabecera 11 (línea ${i + 1})`)
      last = {
        account: account?.account ?? '',
        office: r.slice(6, 10),
        bookingDate: n43Date(r.slice(10, 16)),
        valueDate: n43Date(r.slice(16, 22)),
        commonConcept: r.slice(22, 24),
        ownConcept: r.slice(24, 27),
        amount: signed(r.slice(27, 28), r.slice(28, 42)),
        documentNumber: r.slice(42, 52).trim(),
        reference1: r.slice(52, 64).trim(),
        reference2: r.slice(64, 80).trim(),
        concepts: [],
        fx: null,
        raw: [rec],
      }
      account?.movements.push(last)
      movements.push(last)
    } else if (code === '23') {
      if (!last) {
        warnings.push(`Registro 23 sin movimiento 22 (línea ${i + 1})`)
        continue
      }
      last.raw.push(rec)
      for (const part of [r.slice(4, 42), r.slice(42, 80)]) {
        const t = part.trim()
        if (t) last.concepts.push(t)
      }
    } else if (code === '24') {
      if (!last) {
        warnings.push(`Registro 24 sin movimiento 22 (línea ${i + 1})`)
        continue
      }
      last.raw.push(rec)
      last.fx = { currency: CURRENCIES[r.slice(4, 7)] ?? r.slice(4, 7), amount: cents(r.slice(7, 21)) }
    } else if (code === '33') {
      if (account) {
        account.debitCount = Number(r.slice(20, 25))
        account.debitTotal = cents(r.slice(25, 39))
        account.creditCount = Number(r.slice(39, 44))
        account.creditTotal = cents(r.slice(44, 58))
        account.closing = signed(r.slice(58, 59), r.slice(59, 73))
      }
      last = null
    } else if (code === '88') {
      last = null
    } else {
      warnings.push(`Registro desconocido «${code}» (línea ${i + 1})`)
    }
  }

  for (const a of accounts) {
    if (a.debitCount === null) continue
    const debits = a.movements.filter((m) => m.amount < 0)
    const credits = a.movements.filter((m) => m.amount >= 0)
    if (debits.length !== a.debitCount || credits.length !== a.creditCount)
      warnings.push(`Cuenta ${a.account}: el registro 33 declara ${a.debitCount}/${a.creditCount} apuntes y hay ${debits.length}/${credits.length}`)
    const expected = a.opening + (a.creditTotal ?? 0) - (a.debitTotal ?? 0)
    if (a.closing !== null && expected !== a.closing)
      warnings.push(`Cuenta ${a.account}: saldo final ${a.closing} ≠ inicial + haber − debe (${expected})`)
  }
  return { accounts, movements, warnings }
}
