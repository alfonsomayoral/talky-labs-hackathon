// Light field extraction from Facturae 3.2.x and CFDI 4.0 XML (evidence display only).
import type { EInvoiceSummary } from '@/domain/types'
import { decimalToCents } from './text'
import { at, child, childrenNamed, descendants, parseXml, textAt, type XmlNode } from './xml'

const cents = (s: string | null | undefined): number | null => {
  if (s === null || s === undefined || s.trim() === '') return null
  const [, frac = ''] = s.trim().split('.')
  const v = frac.length <= 2 ? decimalToCents(s) : Math.round(Number(s) * 100)
  return Number.isNaN(v) ? null : v
}
const num = (s: string | null | undefined): number | null => {
  if (s === null || s === undefined || s.trim() === '') return null
  const v = Number(s)
  return Number.isNaN(v) ? null : v
}

function partyName(p: XmlNode | null): string | null {
  const legal = textAt(p, 'LegalEntity/CorporateName')
  if (legal) return legal
  const ind = at(p, 'Individual')
  const parts = ['Name', 'FirstSurname', 'SecondSurname'].map((k) => textAt(ind, k)).filter(Boolean)
  return parts.length ? parts.join(' ') : null
}

function facturae(doc: XmlNode): EInvoiceSummary {
  const inv = descendants(doc, 'Invoice')[0] ?? null
  const seller = at(doc, 'Parties/SellerParty')
  const buyer = at(doc, 'Parties/BuyerParty')
  const totals = at(inv, 'InvoiceTotals')
  const taxes = (node: XmlNode | null, withheld: boolean) =>
    childrenNamed(node, 'Tax').map((t) => ({
      type: textAt(t, 'TaxTypeCode'),
      rate: num(textAt(t, 'TaxRate')),
      base: cents(textAt(t, 'TaxableBase/TotalAmount')),
      amount: cents(textAt(t, 'TaxAmount/TotalAmount')),
      withheld,
    }))
  const corrective = at(inv, 'InvoiceHeader/Corrective')
  const period = at(inv, 'InvoiceIssueData/InvoicingPeriod')
  const iban = descendants(doc, 'IBAN')[0]?.text.trim() || descendants(doc, 'AccountNumber')[0]?.text.trim() || null
  return {
    format: 'facturae',
    version: textAt(doc, 'FileHeader/SchemaVersion'),
    invoiceNumber: textAt(inv, 'InvoiceHeader/InvoiceNumber'),
    series: textAt(inv, 'InvoiceHeader/InvoiceSeriesCode'),
    issueDate: textAt(inv, 'InvoiceIssueData/IssueDate'),
    period: period ? { start: textAt(period, 'StartDate'), end: textAt(period, 'EndDate') } : null,
    currency: textAt(inv, 'InvoiceIssueData/InvoiceCurrencyCode') ?? textAt(doc, 'FileHeader/Batch/InvoiceCurrencyCode'),
    seller: { taxId: textAt(seller, 'TaxIdentification/TaxIdentificationNumber'), name: partyName(seller) },
    buyer: { taxId: textAt(buyer, 'TaxIdentification/TaxIdentificationNumber'), name: partyName(buyer) },
    net: cents(textAt(totals, 'TotalGrossAmountBeforeTaxes')),
    tax: cents(textAt(totals, 'TotalTaxOutputs')),
    withheld: cents(textAt(totals, 'TotalTaxesWithheld')),
    total: cents(textAt(totals, 'InvoiceTotal')),
    retention: cents(textAt(totals, 'AmountsWithheld/WithholdingAmount')),
    payable: cents(textAt(totals, 'TotalExecutableAmount') ?? textAt(totals, 'TotalOutstandingAmount')),
    taxes: [...taxes(at(inv, 'TaxesOutputs'), false), ...taxes(at(inv, 'TaxesWithheld'), true)],
    lines: childrenNamed(at(inv, 'Items'), 'InvoiceLine').map((l) => ({
      description: textAt(l, 'ItemDescription') ?? '',
      quantity: num(textAt(l, 'Quantity')),
      unitPrice: num(textAt(l, 'UnitPriceWithoutTax')),
      amount: cents(textAt(l, 'GrossAmount') ?? textAt(l, 'TotalCost')),
      reference: textAt(l, 'IssuerTransactionReference') ?? textAt(l, 'ReceiverTransactionReference') ?? textAt(l, 'FileReference'),
    })),
    iban,
    corrects: corrective ? { invoiceNumber: textAt(corrective, 'InvoiceNumber'), reason: textAt(corrective, 'ReasonDescription') ?? textAt(corrective, 'ReasonCode') } : null,
    cfdi: null,
    notes: descendants(inv ?? doc, 'InvoiceAdditionalInformation').map((n) => n.text.trim()).filter(Boolean),
  }
}

function cfdi(doc: XmlNode): EInvoiceSummary {
  const a = doc.attrs
  const imp = child(doc, 'Impuestos')
  const subtotal = cents(a.SubTotal)
  const discount = cents(a.Descuento) ?? 0
  const traslados = childrenNamed(child(imp, 'Traslados'), 'Traslado').map((t) => ({
    type: t.attrs.Impuesto ?? null,
    rate: t.attrs.TasaOCuota ? Number(t.attrs.TasaOCuota) * 100 : null,
    base: cents(t.attrs.Base),
    amount: cents(t.attrs.Importe),
    withheld: false,
  }))
  const retenciones = childrenNamed(child(imp, 'Retenciones'), 'Retencion').map((t) => ({
    type: t.attrs.Impuesto ?? null,
    rate: t.attrs.TasaOCuota ? Number(t.attrs.TasaOCuota) * 100 : null,
    base: cents(t.attrs.Base),
    amount: cents(t.attrs.Importe),
    withheld: true,
  }))
  const emisor = child(doc, 'Emisor')
  const receptor = child(doc, 'Receptor')
  const iban = descendants(doc, 'IBAN')[0]?.text.trim() || null
  return {
    format: 'cfdi',
    version: a.Version ?? null,
    invoiceNumber: a.Folio ?? null,
    series: a.Serie ?? null,
    issueDate: a.Fecha ? a.Fecha.slice(0, 10) : null,
    period: null,
    currency: a.Moneda ?? null,
    seller: { taxId: emisor?.attrs.Rfc ?? null, name: emisor?.attrs.Nombre ?? null },
    buyer: { taxId: receptor?.attrs.Rfc ?? null, name: receptor?.attrs.Nombre ?? null },
    net: subtotal === null ? null : subtotal - discount,
    tax: cents(imp?.attrs.TotalImpuestosTrasladados),
    withheld: cents(imp?.attrs.TotalImpuestosRetenidos),
    total: cents(a.Total),
    retention: null,
    payable: cents(a.Total),
    taxes: [...traslados, ...retenciones],
    lines: childrenNamed(child(doc, 'Conceptos'), 'Concepto').map((c) => ({
      description: c.attrs.Descripcion ?? '',
      quantity: num(c.attrs.Cantidad),
      unitPrice: num(c.attrs.ValorUnitario),
      amount: cents(c.attrs.Importe),
      reference: c.attrs.NoIdentificacion ?? null,
    })),
    iban,
    corrects: null,
    cfdi: {
      type: a.TipoDeComprobante ?? null,
      paymentMethod: a.MetodoPago ?? null,
      uuid: descendants(doc, 'TimbreFiscalDigital')[0]?.attrs.UUID ?? null,
      related: descendants(doc, 'CfdiRelacionado').map((r) => r.attrs.UUID).filter((x): x is string => !!x),
    },
    notes: [],
  }
}

/** Parses a Facturae or CFDI document; null for any other XML. */
export function parseEInvoice(xml: string): EInvoiceSummary | null {
  const doc = parseXml(xml)
  if (doc.name === 'Facturae') return facturae(doc)
  if (doc.name === 'Comprobante') return cfdi(doc)
  return null
}
