// ISO 20022 CAMT.053 bank-to-customer statement (any version). Worker-safe.
import { decimalToCents } from './text'
import { at, childrenNamed, descendants, parseXml, textAt, type XmlNode } from './xml'

export interface CamtEntry {
  entryRef: string | null
  /** Signed cents: positive = credit (CRDT). */
  amount: number
  currency: string | null
  bookingDate: string | null
  valueDate: string | null
  status: string | null
  accountServicerRef: string | null
  bankTxCode: string | null
  endToEndIds: string[]
  instructionIds: string[]
  counterparty: string | null
  unstructured: string[]
  structuredRefs: string[]
  /** The `<Ntry>` element as it appears in the file. */
  raw: string
}

export interface CamtStatement {
  id: string | null
  iban: string | null
  currency: string | null
  opening: number | null
  closing: number | null
  entries: CamtEntry[]
  warnings: string[]
}

const date = (n: XmlNode | null) => textAt(n, 'Dt') ?? textAt(n, 'DtTm')?.slice(0, 10) ?? null
const signedAmount = (amt: string | null, ind: string | null) => {
  const c = decimalToCents(amt ?? '')
  return ind === 'DBIT' ? -c : c
}

function balance(stmt: XmlNode, codes: string[]): number | null {
  for (const b of childrenNamed(stmt, 'Bal')) {
    const code = textAt(b, 'Tp/CdOrPrtry/Cd') ?? textAt(b, 'Tp/CdOrPrtry/Prtry')
    if (code && codes.includes(code)) return signedAmount(textAt(b, 'Amt'), textAt(b, 'CdtDbtInd'))
  }
  return null
}

export function parseCamt053(xml: string): CamtStatement {
  const doc = parseXml(xml)
  const stmt = descendants(doc, 'Stmt')[0]
  const warnings: string[] = []
  if (!stmt) return { id: null, iban: null, currency: null, opening: null, closing: null, entries: [], warnings: ['CAMT.053 sin <Stmt>'] }

  const entries = childrenNamed(stmt, 'Ntry').map((n): CamtEntry => {
    const amtNode = at(n, 'Amt')
    const amount = signedAmount(amtNode?.text ?? null, textAt(n, 'CdtDbtInd'))
    if (Number.isNaN(amount)) warnings.push(`Importe ilegible en ${textAt(n, 'NtryRef') ?? 'Ntry'}`)
    const txs = descendants(n, 'TxDtls')
    const refs = txs.map((t) => at(t, 'Refs'))
    const parties = txs.flatMap((t) => [textAt(t, 'RltdPties/Dbtr/Nm') ?? textAt(t, 'RltdPties/Dbtr/Pty/Nm'), textAt(t, 'RltdPties/Cdtr/Nm') ?? textAt(t, 'RltdPties/Cdtr/Pty/Nm')])
    return {
      entryRef: textAt(n, 'NtryRef'),
      amount,
      currency: amtNode?.attrs.Ccy ?? null,
      bookingDate: date(at(n, 'BookgDt')),
      valueDate: date(at(n, 'ValDt')),
      status: textAt(n, 'Sts/Cd') ?? textAt(n, 'Sts'),
      accountServicerRef: textAt(n, 'AcctSvcrRef') ?? refs.map((r) => textAt(r, 'AcctSvcrRef')).find(Boolean) ?? null,
      bankTxCode: textAt(n, 'BkTxCd/Prtry/Cd') ?? textAt(n, 'BkTxCd/Domn/Cd'),
      endToEndIds: refs.map((r) => textAt(r, 'EndToEndId')).filter((x): x is string => !!x),
      instructionIds: refs.map((r) => textAt(r, 'InstrId')).filter((x): x is string => !!x),
      counterparty: parties.find(Boolean) ?? null,
      unstructured: descendants(n, 'Ustrd').map((u) => u.text.trim()).filter(Boolean),
      structuredRefs: descendants(n, 'CdtrRefInf').map((c) => textAt(c, 'Ref')).filter((x): x is string => !!x),
      raw: xml.slice(n.start, n.end),
    }
  })

  return {
    id: textAt(stmt, 'Id'),
    iban: textAt(stmt, 'Acct/Id/IBAN'),
    currency: textAt(stmt, 'Acct/Ccy'),
    opening: balance(stmt, ['OPBD', 'PRCD']),
    closing: balance(stmt, ['CLBD']),
    entries,
    warnings,
  }
}
