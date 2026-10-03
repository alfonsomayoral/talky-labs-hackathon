// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { DEV_PHASE, hasDev, readText } from '../testing/nodeData'
import { parseEInvoice } from './einvoice'
import { parseXml, textAt } from './xml'

describe('xml reader', () => {
  it('handles namespaces, attributes, entities, CDATA and comments', () => {
    const doc = parseXml('<?xml version="1.0"?><!-- c --><a:Root xmlns:a="u"><B x="1 &amp; 2">t &lt;b&gt;</B><C/><D><![CDATA[<raw>]]></D></a:Root>')
    expect(doc.name).toBe('Root')
    expect(doc.children.map((c) => c.name)).toEqual(['B', 'C', 'D'])
    expect(doc.children[0].attrs.x).toBe('1 & 2')
    expect(textAt(doc, 'B')).toBe('t <b>')
    expect(textAt(doc, 'D')).toBe('<raw>')
  })
})

describe.skipIf(!hasDev)('e-invoices from the inbox', () => {
  it('extracts Facturae 3.2.2 fields', () => {
    const inv = parseEInvoice(readText(`${DEV_PHASE}/inbox/ap/API004091/facturae_2026-035925.xml`))!
    expect(inv).toMatchObject({
      format: 'facturae',
      version: '3.2.2',
      invoiceNumber: '2026-035925',
      issueDate: '2026-07-07',
      currency: 'EUR',
      seller: { taxId: 'A93432007' },
      buyer: { taxId: 'A12359962', name: 'Kalmora Construcción, S.A.U.' },
      net: 12449684,
      tax: 0,
      total: 12449684,
      retention: 622484,
      payable: 11827200,
      iban: null,
    })
    expect(inv.lines).toHaveLength(3)
    expect(inv.lines[0]).toMatchObject({ amount: 2861320, reference: '4500021222', quantity: 1540 })
  })

  it('extracts CFDI 4.0 fields', () => {
    const inv = parseEInvoice(readText(`${DEV_PHASE}/inbox/ap/API004320/27CE25E7-1FA1-4858-B8F4-C1CF128ECCBF.xml`))!
    expect(inv).toMatchObject({
      format: 'cfdi',
      version: '4.0',
      series: 'N20',
      invoiceNumber: 'N20263292',
      issueDate: '2026-07-01',
      currency: 'MXN',
      seller: { taxId: 'CON940404PLJ' },
      buyer: { taxId: 'KMI91110719K' },
      net: 198774891,
      tax: 31803983,
      total: 230578874,
      cfdi: { type: 'I', paymentMethod: 'PPD', uuid: '27CE25E7-1FA1-4858-B8F4-C1CF128ECCBF', related: [] },
    })
    expect(inv.taxes[0]).toMatchObject({ rate: 16, base: 198774891 })
  })

  it('reads the corrective block of a credit note', () => {
    const inv = parseEInvoice(readText(`${DEV_PHASE}/inbox/ap/API005587/facturae_R-2026-007088.xml`))!
    expect(inv.corrects?.invoiceNumber).toBe('2026-006999')
  })
})
