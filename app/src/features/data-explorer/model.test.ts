import { describe, expect, it } from 'vitest'
import type { DatasetCore, WorkItem } from '@/domain/types'
import { bankLineItems, customerLinks, dataPath, fileKind, itemsCiting, itemsCitingEntry, journalFilters, journalParams, partnerPath, prettyJson, prettyXml, vendorLinks } from './model'

const item = (id: string, evidence: WorkItem['evidence']): WorkItem => ({ id, evidence }) as WorkItem

describe('journal filters in the URL', () => {
  it('round-trips through Spanish query params and drops empty values', () => {
    const filters = { company: '1100', account: '40000000', source: 'AP', from: '2026-07-01', to: '2026-07-31', text: 'eg-019592' }
    const params = journalParams({ ...filters, text: ` ${filters.text} ` })
    expect(params.toString()).toBe('sociedad=1100&cuenta=40000000&origen=AP&desde=2026-07-01&hasta=2026-07-31&q=eg-019592')
    expect(journalFilters(params)).toEqual(filters)
    expect(journalFilters(new URLSearchParams('cuenta=&q=%20'))).toEqual({})
    expect(dataPath.journal({})).toBe('/datos/diario')
    expect(dataPath.journal({ account: '57200000' })).toBe('/datos/diario?cuenta=57200000')
  })
})

describe('cross-links', () => {
  const core = {
    vendors: [{ id: 'V1' }],
    customers: [{ id: 'C1' }],
    apInvoices: [
      { doc_id: 'A', vendor: 'V1', issue_date: '2026-05-01' },
      { doc_id: 'B', vendor: 'V2', issue_date: '2026-06-01' },
      { doc_id: 'C', vendor: 'V1', issue_date: '2026-06-15' },
    ],
    apDocumentLog: [{ doc_id: 'A', vendor: 'V1', received_on: '2026-05-02' }],
    purchaseOrders: [{ id: 'PO1', vendor: 'V1', created_on: '2026-04-01' }],
    contractorCertificates: [{ vendor: 'V1', reference: 'R' }],
    salesContracts: [{ id: 'K1', customer: 'C1' }],
    arInvoices: [{ id: 'F1', customer: 'C1', date: '2026-06-30' }],
    openItems: [{ partner: 'C1', assignment: 'F1' }, { partner: 'V1', assignment: 'X' }],
    promissoryNotes: [],
  } as unknown as DatasetCore

  it('gathers a vendor history, newest first', () => {
    const v = vendorLinks(core, 'V1')
    expect(v.invoices.map((i) => i.doc_id)).toEqual(['C', 'A'])
    expect(v.documentLog).toHaveLength(1)
    expect(v.purchaseOrders.map((p) => p.id)).toEqual(['PO1'])
    expect(v.certificates).toHaveLength(1)
  })

  it('gathers a customer with contracts, invoices and open items', () => {
    const c = customerLinks(core, 'C1')
    expect(c.contracts.map((k) => k.id)).toEqual(['K1'])
    expect(c.invoices.map((i) => i.id)).toEqual(['F1'])
    expect(c.openItems.map((o) => o.assignment)).toEqual(['F1'])
  })

  it('resolves journal partners to their master page', () => {
    expect(partnerPath(core, 'V1')).toBe('/datos/proveedores/V1')
    expect(partnerPath(core, 'C1')).toBe('/datos/clientes/C1')
    expect(partnerPath(core, '1200')).toBeNull()
    expect(partnerPath(core, null)).toBeNull()
  })

  it('finds the items that cite a master record or a journal entry', () => {
    const items = [
      item('ap:A', [{ kind: 'erp', file: 'erp/vendors.jsonl', key: 'V1' }]),
      item('ap:B', [{ kind: 'erp', file: 'erp/vendors.jsonl', key: 'V10' }]),
      item('bank_rec:BIN/BL1', [{ kind: 'journal', book_line: 'JE-1#2' }]),
      item('bank_rec:BIN/BL2', [{ kind: 'journal', book_line: 'JE-10#1' }]),
    ]
    expect(itemsCiting(items, 'erp/vendors.jsonl', 'V1').map((i) => i.id)).toEqual(['ap:A'])
    expect(itemsCitingEntry(items, 'JE-1').map((i) => i.id)).toEqual(['bank_rec:BIN/BL1'])
  })

  it('links a statement line to the items it feeds', () => {
    const byId = new Map([
      ['ar_cash:BL1', item('ar_cash:BL1', [])],
      ['bank_rec:BIN-1100/BL1', item('bank_rec:BIN-1100/BL1', [])],
    ])
    expect(bankLineItems(byId, 'BIN-1100', 'BL1').map((i) => i.id)).toEqual(['ar_cash:BL1', 'bank_rec:BIN-1100/BL1'])
    expect(bankLineItems(byId, 'BIN-1100', 'BL2')).toEqual([])
    expect(bankLineItems(null, 'BIN-1100', 'BL1')).toEqual([])
  })
})

describe('files', () => {
  it('detects the viewer for each inbox file', () => {
    expect(fileKind('inbox/ap/API004093/factura_EG-019592.pdf')).toBe('pdf')
    expect(fileKind('inbox/ap/X/factura.XML')).toBe('xml')
    expect(fileKind('inbox/ap/X/message.json')).toBe('json')
    expect(fileKind('inbox/ar/remittances/face.csv')).toBe('text')
    expect(fileKind('inbox/ar/x.png')).toBe('other')
  })

  it('indents XML and keeps text-only elements on one line', () => {
    const xml = '<?xml version="1.0"?><a x="1"><b>uno</b><c><d/></c>\n  <e>dos</e></a>'
    expect(prettyXml(xml)).toBe(['<?xml version="1.0"?>', '<a x="1">', '  <b>uno</b>', '  <c>', '    <d/>', '  </c>', '  <e>dos</e>', '</a>'].join('\n'))
    expect(prettyXml('<a><b>')).toBe('<a><b>')
  })

  it('pretty-prints JSON and leaves invalid JSON untouched', () => {
    expect(prettyJson('{"a":1}')).toBe('{\n  "a": 1\n}')
    expect(prettyJson('{oops')).toBe('{oops')
  })
})
