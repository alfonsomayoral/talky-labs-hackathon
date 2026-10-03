import { describe, expect, it } from 'vitest'
import type { ApRow, Company, EInvoiceSummary, GoodsReceipt, PurchaseOrder, Vendor, WorkItem } from '@/domain/types'
import { actionDetails, apListRows, apSankey, duplicateTarget, EMPTY_FILTER, facetCounts, filterRows, lineMatches, masterCompare, NO_REASON, overTolerance, textDiff } from './model'

const row = (over: Partial<ApRow>): ApRow =>
  ({
    doc_id: 'D1',
    document_type: 'INVOICE',
    decision: 'POST',
    reasons: [],
    company: '1100',
    vendor_id: 'V1',
    invoice_number: 'F-1',
    invoice_date: '2026-07-01',
    currency: 'EUR',
    net: 100,
    tax: 21,
    gross: 121,
    withholding: 0,
    retention: 0,
    payable: 121,
    duplicate_of: null,
    payee: null,
    payment_block: null,
    action: null,
    lines: [],
    journal_entry: null,
    ...over,
  }) as ApRow

const item = (r: ApRow, rowIndex: number): WorkItem => ({
  id: `ap:${r.doc_id}`,
  task: 'ap',
  key: r.doc_id,
  company: r.company,
  title: r.doc_id,
  counterparty: null,
  amount: r.gross,
  currency: 'EUR',
  date: null,
  status: 'AUTO',
  outcome: r.decision,
  reasons: r.reasons,
  confidence: null,
  provenance: 'RULE',
  policyRefs: [],
  evidence: [],
  tbImpact: 0,
  rowIndex,
})

const vendor = (over: Partial<Vendor> = {}): Vendor =>
  ({
    id: 'V1',
    name: 'Áridos',
    tax_id: 'B94901377',
    vat_id: 'ESB94901377',
    currency: 'EUR',
    withholding: null,
    bank: { iban: 'ES8138797130972457481766' },
    bank_history: [],
    companies: ['1100'],
    ...over,
  }) as Vendor

const company = { code: '1100', tax_id: 'A12345678', vat_id: 'ESA12345678' } as Company

const einvoice = (over: Partial<EInvoiceSummary> = {}): EInvoiceSummary =>
  ({
    seller: { taxId: 'ESB94901377', name: 'Áridos' },
    buyer: { taxId: 'A12345678', name: 'Kalmora' },
    iban: 'ES8138797130972457481766',
    currency: 'EUR',
    withheld: 0,
    ...over,
  }) as EInvoiceSummary

describe('apSankey', () => {
  it('links each document type to its decisions in policy order', () => {
    const s = apSankey([
      row({ document_type: 'CREDIT_NOTE', decision: 'POST' }),
      row({ decision: 'DUPLICATE' }),
      row({ decision: 'POST' }),
      row({ decision: 'POST' }),
      row({ document_type: 'PROFORMA', decision: 'NOT_INVOICE' }),
    ])
    expect(s.types.map((t) => [t.key, t.count])).toEqual([
      ['INVOICE', 3],
      ['CREDIT_NOTE', 1],
      ['PROFORMA', 1],
    ])
    expect(s.decisions.map((d) => d.key)).toEqual(['POST', 'DUPLICATE', 'NOT_INVOICE'])
    expect(s.links.find((l) => l.type === 'INVOICE' && l.decision === 'POST')?.count).toBe(2)
    expect(s.links.reduce((a, l) => a + l.count, 0)).toBe(5)
  })
})

describe('facets', () => {
  const rows = [
    row({ doc_id: 'A', decision: 'HOLD', reasons: ['BANK_DETAILS_CHANGED'] }),
    row({ doc_id: 'B', decision: 'HOLD', reasons: ['PRICE_VARIANCE', 'QTY_NOT_RECEIVED'] }),
    row({ doc_id: 'C', decision: 'POST' }),
    row({ doc_id: 'D', decision: 'REJECT', reasons: ['ARITHMETIC_ERROR'] }),
  ]
  const list = apListRows(rows.map(item), rows)

  it('filters by decision and reason (any reason matches)', () => {
    expect(filterRows(list, { ...EMPTY_FILTER, decisions: ['HOLD'] }).map((r) => r.row.doc_id)).toEqual(['A', 'B'])
    expect(filterRows(list, { ...EMPTY_FILTER, reasons: ['QTY_NOT_RECEIVED'] }).map((r) => r.row.doc_id)).toEqual(['B'])
    expect(filterRows(list, { ...EMPTY_FILTER, reasons: [NO_REASON] }).map((r) => r.row.doc_id)).toEqual(['C'])
  })

  it('restricts to the items of a selected branch', () => {
    expect(filterRows(list, { ...EMPTY_FILTER, only: new Set(['ap:D']) }).map((r) => r.row.doc_id)).toEqual(['D'])
  })

  it('counts each facet ignoring its own selection', () => {
    const c = facetCounts(list, { ...EMPTY_FILTER, decisions: ['HOLD'] })
    expect(c.decisions.get('POST')).toBe(1)
    expect(c.reasons.get('PRICE_VARIANCE')).toBe(1)
    expect(c.reasons.has('ARITHMETIC_ERROR')).toBe(false)
  })
})

describe('masterCompare', () => {
  const base = { row: row({}), company, certificates: [], sender: null }
  const iban = (fields: ReturnType<typeof masterCompare>) => fields.find((f) => f.id === 'iban')!

  it('accepts an IBAN equal to the master one', () => {
    expect(iban(masterCompare({ ...base, vendor: vendor(), einvoice: einvoice() })).state).toBe('match')
  })

  it('flags an IBAN that is neither in the master nor a registered factor (possible fraud)', () => {
    const f = iban(masterCompare({ ...base, vendor: vendor(), einvoice: einvoice({ iban: 'ES1200000000000000000000' }) }))
    expect(f.state).toBe('mismatch')
  })

  it('explains an IBAN that belongs to the registered factor', () => {
    const v = vendor({ alternative_payee: { type: 'FACTOR', name: 'Factor SA', iban: 'ES99 0000 1111', from_date: '2026-01-01' } })
    expect(iban(masterCompare({ ...base, vendor: v, einvoice: einvoice({ iban: 'ES9900001111' }) })).state).toBe('explained')
  })

  it('takes the agent decision when the document has no readable IBAN', () => {
    const f = iban(masterCompare({ ...base, row: row({ reasons: ['BANK_DETAILS_CHANGED'] }), vendor: vendor(), einvoice: null }))
    expect(f.state).toBe('mismatch')
  })

  it('matches tax ids with or without the country prefix and marks unknown vendors', () => {
    const fields = masterCompare({ ...base, vendor: vendor(), einvoice: einvoice() })
    expect(fields.find((f) => f.id === 'seller_tax_id')?.state).toBe('match')
    expect(fields.find((f) => f.id === 'addressee')?.state).toBe('match')
    expect(masterCompare({ ...base, vendor: null, einvoice: null })[0].state).toBe('mismatch')
  })

  it('compares the sender domain with the vendor email', () => {
    const v = vendor({ email: 'facturacion@ffiinstalacionesel.es' })
    const sender = (s: string) => masterCompare({ ...base, vendor: v, einvoice: null, sender: s }).find((f) => f.id === 'sender')?.state
    expect(sender('facturacion@ffiinstalacionesel-es.es')).toBe('mismatch')
    expect(sender('Facturacion@FFIinstalacionesel.es')).toBe('match')
    expect(masterCompare({ ...base, vendor: v, einvoice: null }).some((f) => f.id === 'sender')).toBe(false)
  })

  it('checks the art. 43 certificate at the invoice date', () => {
    const certs = [{ vendor: 'V1', issued_on: '2025-01-01', valid_until: '2026-06-30', reference: 'X' }]
    const f = masterCompare({ ...base, vendor: vendor(), einvoice: null, certificates: certs }).find((x) => x.id === 'certificate')
    expect(f?.state).toBe('mismatch')
    expect(f?.master).toBe('Vigente hasta 30 jun 2026')
  })
})

describe('lineMatches', () => {
  const po = { id: 'P1', items: [{ item: 10, description: 'Árido', quantity_milli: 10_000, unit_price: 10_000 }] } as PurchaseOrder
  const gr = (id: string, amount: number, qty = 1000): GoodsReceipt => ({ id, po: 'P1', po_item: 10, amount, quantity_milli: qty }) as GoodsReceipt
  const line = (amount: number, extra: Record<string, unknown> = {}) => ({ amount, account: '60000000', cost_center: null, wbs: null, tax_code: 'S21', po: 'P1', po_item: 10, ...extra })

  it('classifies each line against its receipts and the tolerance', () => {
    const [ok, within, over, none, free] = lineMatches(
      [line(10_000, { goods_receipts: ['G1'] }), line(10_100, { goods_receipts: ['G1'] }), line(30_000, { goods_receipts: ['G1'] }), line(5_000, { goods_receipts: [] }), { ...line(1), po: null }],
      [po],
      [gr('G1', 10_000)],
    )
    expect(ok.state).toBe('ok')
    expect(within.state).toBe('within_tolerance')
    expect(over.state).toBe('price_variance')
    expect(over.variance).toBe(20_000)
    expect(none.state).toBe('not_received')
    expect(free.state).toBe('no_po')
  })

  it('falls back to every receipt of the PO item when the line does not list them', () => {
    const [m] = lineMatches([line(20_000)], [po], [gr('G1', 10_000), gr('G2', 10_000), { ...gr('G3', 5), po_item: 20 }])
    expect(m.receipts.map((g) => g.id)).toEqual(['G1', 'G2'])
    expect(m.state).toBe('ok')
  })

  it('applies both tolerance limits', () => {
    expect(overTolerance(15_001, 10_000_000)).toBe(true)
    expect(overTolerance(201, 10_000)).toBe(true)
    expect(overTolerance(200, 10_000)).toBe(false)
  })
})

describe('duplicateTarget', () => {
  const rows = [row({ doc_id: 'A' }), row({ doc_id: 'B', decision: 'DUPLICATE', duplicate_of: 'A' }), row({ doc_id: 'C', duplicate_of: 'H1' })]
  const history = { apInvoices: [{ doc_id: 'H1' }] as never[], apDocumentLog: [] }

  it('points to a document of the month, to the history, or reports it missing', () => {
    expect(duplicateTarget('A', rows, history)?.kind).toBe('month')
    expect(duplicateTarget('H1', rows, history)?.kind).toBe('history')
    expect(duplicateTarget('ZZ', rows, history)?.kind).toBe('missing')
    expect(duplicateTarget(null, rows, history)).toBeNull()
  })
})

describe('actionDetails', () => {
  it('spells out an embargo with its reference and amount', () => {
    expect(actionDetails({ ref: '20263092743099K', amount: 6193020 })).toEqual([
      { label: 'Referencia', value: '20263092743099K', kind: 'mono' },
      { label: 'Importe', value: 6193020, kind: 'money' },
    ])
  })

  it('formats dates, IBANs and flags of a bank details change', () => {
    expect(actionDetails({ old_iban: 'ES52', new_iban: 'ES27', certificate: true, effective: '2026-09-22' })).toEqual([
      { label: 'IBAN anterior', value: 'ES52', kind: 'mono' },
      { label: 'IBAN nuevo', value: 'ES27', kind: 'mono' },
      { label: 'Certificado bancario', value: 'Sí', kind: 'text' },
      { label: 'Desde', value: '22 sept 2026', kind: 'text' },
    ])
  })

  it('keeps unknown fields and returns nothing without data', () => {
    expect(actionDetails({ valid_days: 30, extra: 'x' })).toEqual([
      { label: 'Validez', value: '30 días', kind: 'text' },
      { label: 'extra', value: 'x', kind: 'text' },
    ])
    expect(actionDetails(null)).toEqual([])
  })
})

describe('textDiff', () => {
  it('isolates the characters a look-alike domain changes', () => {
    expect(textDiff('señalizaci0nesvial.es', 'señalizacionesvial.es')).toEqual({ before: 'señalizaci', changed: '0', after: 'nesvial.es' })
    expect(textDiff('ffiinstalacionesel-es.es', 'ffiinstalacionesel.es')).toEqual({ before: 'ffiinstalacionesel', changed: '-es', after: '.es' })
  })

  it('returns the whole text when nothing is shared, and nothing changed when equal', () => {
    expect(textDiff('ES11', 'PT22').changed).toBe('ES11')
    expect(textDiff('V1', 'V1').changed).toBe('')
  })
})
