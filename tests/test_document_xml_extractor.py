from dataclasses import replace
import os
from pathlib import Path
import tempfile
import unittest

from kalmora.documents.classification import classify_document
from kalmora.documents.contracts import ParsedBlock, digest
from kalmora.documents.normalization import normalize_document_facts
from kalmora.documents.router import DocumentRouter
from kalmora.documents.xml_extractor import XMLDocumentExtractor, XMLExtractionError


FACTURAE = """<fe:Facturae xmlns:fe="urn:facturae">
<FileHeader><SchemaVersion>3.2.2</SchemaVersion></FileHeader>
<Parties><SellerParty><TaxIdentification><TaxIdentificationNumber>ES-A123</TaxIdentificationNumber></TaxIdentification>
<LegalEntity><CorporateName>Supplier</CorporateName></LegalEntity></SellerParty>
<BuyerParty><TaxIdentification><TaxIdentificationNumber>ES-B456</TaxIdentificationNumber></TaxIdentification></BuyerParty></Parties>
<Invoices><Invoice><InvoiceHeader><InvoiceNumber>NEW-7</InvoiceNumber><InvoiceSeriesCode>A</InvoiceSeriesCode>
<InvoiceDocumentType>FC</InvoiceDocumentType><InvoiceClass>OO</InvoiceClass></InvoiceHeader>
<InvoiceIssueData><IssueDate>2026-09-13</IssueDate><InvoiceCurrencyCode>EUR</InvoiceCurrencyCode></InvoiceIssueData>
<TaxesOutputs><Tax><TaxTypeCode>01</TaxTypeCode><TaxRate>21.00</TaxRate>
<TaxableBase><TotalAmount>100.00</TotalAmount></TaxableBase><TaxAmount><TotalAmount>21.00</TotalAmount></TaxAmount></Tax>
<Tax><TaxTypeCode>99</TaxTypeCode><TaxRate>2.00</TaxRate></Tax></TaxesOutputs>
<TaxesWithheld><Tax><TaxTypeCode>04</TaxTypeCode><TaxRate>15.00</TaxRate><TaxAmount><TotalAmount>15.00</TotalAmount></TaxAmount></Tax></TaxesWithheld>
<InvoiceTotals><TotalGrossAmountBeforeTaxes>100.00</TotalGrossAmountBeforeTaxes><TotalTaxOutputs>21.00</TotalTaxOutputs>
<TotalTaxesWithheld>15.00</TotalTaxesWithheld><InvoiceTotal>106.00</InvoiceTotal><TotalOutstandingAmount>50.00</TotalOutstandingAmount></InvoiceTotals>
<Items><InvoiceLine><ItemDescription>Original line</ItemDescription><Quantity>2.000</Quantity>
<UnitPriceWithoutTax>50.000000</UnitPriceWithoutTax><GrossAmount>100.00</GrossAmount>
<TaxesOutputs><Tax><TaxTypeCode>01</TaxTypeCode><TaxRate>21.00</TaxRate></Tax></TaxesOutputs></InvoiceLine>
<InvoiceLine><ItemDescription>Second</ItemDescription><Quantity>0.125</Quantity><UnitPriceWithoutTax>2.1234</UnitPriceWithoutTax></InvoiceLine></Items>
<PaymentDetails><Installment><InstallmentDueDate>2026-10-13</InstallmentDueDate><InstallmentAmount>106.00</InstallmentAmount>
<AccountToBeCredited><IBAN>ES 123</IBAN></AccountToBeCredited></Installment></PaymentDetails>
<AdditionalData><UnmappedField>Do not discard</UnmappedField><EmptyField/></AdditionalData>
</Invoice></Invoices></fe:Facturae>"""

CFDI = """<cfdi:Comprobante xmlns:cfdi="urn:cfdi" Version="4.0" Folio="A-7" Serie="A-"
Fecha="2026-09-13T12:01:00" Moneda="MXN" TipoDeComprobante="I" SubTotal="100.00" Total="105.33">
<cfdi:Emisor Rfc="AAA010101ABC" Nombre="Supplier"/><cfdi:Receptor Rfc="BBB020202DEF" Nombre="Buyer"/>
<cfdi:Conceptos><cfdi:Concepto Cantidad="0.125" ValorUnitario="800.0000" Descripcion="Line" Importe="100.00">
<cfdi:Impuestos><cfdi:Traslados><cfdi:Traslado Base="100.00" Importe="16.00" Impuesto="002" TasaOCuota="0.160000" TipoFactor="Tasa"/></cfdi:Traslados>
<cfdi:Retenciones><cfdi:Retencion Base="100.00" Importe="10.67" Impuesto="002" TasaOCuota="0.106700" TipoFactor="Tasa"/></cfdi:Retenciones></cfdi:Impuestos>
</cfdi:Concepto></cfdi:Conceptos>
<cfdi:Impuestos TotalImpuestosTrasladados="16.00" TotalImpuestosRetenidos="10.67">
<cfdi:Traslados><cfdi:Traslado Base="100.00" Importe="16.00" Impuesto="002" TasaOCuota="0.160000" TipoFactor="Tasa"/></cfdi:Traslados>
<cfdi:Retenciones><cfdi:Retencion Importe="10.67" Impuesto="002"/></cfdi:Retenciones></cfdi:Impuestos>
<cfdi:Complemento><TimbreFiscalDigital UUID="new-uuid"/></cfdi:Complemento></cfdi:Comprobante>"""


class XMLExtractorTests(unittest.IsolatedAsyncioTestCase):
    def parse(self, xml, name="unknown.xml"):
        with tempfile.TemporaryDirectory() as tmp:
            phase = Path(tmp)
            relative = "inbox/ap/new/" + name
            path = phase / relative
            path.parent.mkdir(parents=True)
            path.write_text(xml, encoding="utf-8")
            return DocumentRouter(phase).parse(relative)

    async def test_facturae_source_units_taxes_withheld_and_payable_are_distinct(self):
        document = self.parse(FACTURAE)
        facts = await XMLDocumentExtractor().extract(document)
        self.assertEqual(facts.source_sha256, digest(FACTURAE.encode()))
        self.assertEqual(facts.fields["raw.invoice_document_type"][0].value, "FC")
        self.assertEqual(facts.fields["raw.invoice_class"][0].value, "OO")
        self.assertNotIn("document_type", facts.fields)
        normalized = normalize_document_facts(facts)
        self.assertEqual(normalized.diagnostics, ())
        expected = {"net_cents": 10000, "tax_cents": 2100, "withholding_cents": 1500,
                    "payable_cents": 5000, "line.1.quantity_milli": 2000,
                    "line.1.unit_price_e4": 500000, "line.2.quantity_milli": 125,
                    "tax.charge.1.tax_rate_e4": 2100, "tax.charge.2.tax_rate_e4": 200,
                    "tax.withheld.1.tax_rate_e4": 1500, "line.1.tax.charge.1.tax_rate_e4": 2100,
                    "payment.1.due_date": "2026-10-13"}
        for name, value in expected.items():
            self.assertEqual(normalized.facts.fields[name][0].value, value, name)
        self.assertNotIn("gross", facts.fields)
        self.assertNotIn("po_reference", facts.fields)
        raw_total = facts.fields["raw.xml./Facturae/Invoices[1]/Invoice[1]/InvoiceTotals[1]/TotalOutstandingAmount[1]"][0]
        self.assertEqual(raw_total.value, "50.00")

    async def test_cfdi_uses_literal_kind_and_never_duplicates_series(self):
        facts = await XMLDocumentExtractor().extract(self.parse(CFDI))
        self.assertEqual(facts.fields["document_number"][0].value, "A-7")
        self.assertEqual(facts.fields["raw.series"][0].value, "A-")
        self.assertEqual(facts.fields["raw.cfdi_type"][0].evidence.quote, "I")
        self.assertEqual(classify_document(facts).document_type, "INVOICE")
        normalized = normalize_document_facts(facts)
        self.assertEqual(normalized.diagnostics, ())
        self.assertEqual(normalized.facts.fields["tax.charge.1.tax_rate_e4"][0].value, 1600)
        self.assertEqual(normalized.facts.fields["line.1.tax.withheld.1.tax_rate_e4"][0].value, 1067)
        self.assertEqual(normalized.facts.fields["payable_cents"][0].value, 10533)
        credit = await XMLDocumentExtractor().extract(self.parse(CFDI.replace('TipoDeComprobante="I"', 'TipoDeComprobante="E"')))
        self.assertEqual(classify_document(credit).document_type, "CREDIT_NOTE")
        unsupported = await XMLDocumentExtractor().extract(self.parse(CFDI.replace('TipoDeComprobante="I"', 'TipoDeComprobante="P"')))
        self.assertEqual(classify_document(unsupported).status, "UNKNOWN")

    async def test_facturae_corrective_and_line_references_keep_their_roles_and_signs(self):
        correction = """<Corrective><InvoiceNumber>OLD-3</InvoiceNumber><InvoiceSeriesCode>Z</InvoiceSeriesCode>
        <ReasonCode>01</ReasonCode><ReasonDescription>Refund</ReasonDescription><CorrectionMethod>02</CorrectionMethod>
        <TaxPeriod><StartDate>2026-01-01</StartDate><EndDate>2026-01-31</EndDate></TaxPeriod></Corrective>"""
        references = """<IssuerTransactionReference>SUPPLIER-REFERENCE</IssuerTransactionReference>
        <ReceiverTransactionReference>CONTRACT-OR-ORDER</ReceiverTransactionReference><SequenceNumber>10.0</SequenceNumber>
        <DeliveryNotesReferences><DeliveryNote><DeliveryNoteNumber>DEL-1</DeliveryNoteNumber><DeliveryNoteDate>2026-09-01</DeliveryNoteDate></DeliveryNote>
        <DeliveryNote><DeliveryNoteNumber>DEL-2</DeliveryNoteNumber></DeliveryNote></DeliveryNotesReferences>"""
        xml = FACTURAE.replace("</InvoiceHeader>", correction + "</InvoiceHeader>")
        xml = xml.replace("<ItemDescription>Original line", references + "<ItemDescription>Original line")
        xml = xml.replace("<TotalGrossAmountBeforeTaxes>100.00", "<TotalGrossAmountBeforeTaxes>-100.00")
        facts = await XMLDocumentExtractor().extract(self.parse(xml))
        self.assertEqual(facts.fields["corrective.document_number"][0].value, "OLD-3")
        self.assertEqual(facts.fields["corrective.series"][0].value, "Z")
        self.assertEqual(facts.fields["document_number"][0].value, "NEW-7")
        self.assertEqual(facts.fields["line.1.receiver_transaction_reference"][0].value, "CONTRACT-OR-ORDER")
        self.assertEqual(facts.fields["line.1.order_sequence"][0].value, "10.0")
        self.assertEqual(facts.fields["line.1.delivery.2.document_number"][0].value, "DEL-2")
        self.assertNotIn("po_reference", facts.fields)
        self.assertNotIn("receipt_id", facts.fields)
        self.assertEqual(facts.fields["net"][0].value, "-100.00")
        normalized = normalize_document_facts(facts)
        self.assertEqual(normalized.facts.fields["net_cents"][0].value, -10000)
        self.assertEqual(normalized.facts.fields["corrective.period_start"][0].value, "2026-01-01")
        header = xml.replace("</InvoiceIssueData>", "<ReceiverTransactionReference>PO-EXPLICIT</ReceiverTransactionReference></InvoiceIssueData>")
        direct = await XMLDocumentExtractor().extract(self.parse(header))
        self.assertEqual(direct.fields["po_reference"][0].value, "PO-EXPLICIT")

    async def test_cfdi_related_groups_keep_every_uuid_without_assuming_credit_originals(self):
        groups = """<cfdi:CfdiRelacionados TipoRelacion="01"><cfdi:CfdiRelacionado UUID="old-1"/>
        <cfdi:CfdiRelacionado UUID="old-2"/></cfdi:CfdiRelacionados>
        <cfdi:CfdiRelacionados TipoRelacion="07"><cfdi:CfdiRelacionado UUID="advance-1"/></cfdi:CfdiRelacionados>"""
        facts = await XMLDocumentExtractor().extract(self.parse(CFDI.replace("<cfdi:Emisor", groups + "<cfdi:Emisor")))
        for key, value in {"related.1.relationship_code": "01", "related.1.document.1.uuid": "old-1",
                           "related.1.document.2.uuid": "old-2", "related.2.relationship_code": "07",
                           "related.2.document.1.uuid": "advance-1"}.items():
            self.assertEqual(facts.fields[key][0].value, value)
            self.assertEqual(facts.fields[key][0].evidence.quote, value)
        self.assertEqual(facts.fields["raw.cfdi_uuid"][0].value, "new-uuid")
        self.assertNotIn("corrective.document_number", facts.fields)

    async def test_cfdi_fixed_quotas_and_unknown_factors_are_not_rates(self):
        for replacement in ('TipoFactor="Cuota"', 'TipoFactor="Exento"', ''):
            facts = await XMLDocumentExtractor().extract(self.parse(CFDI.replace('TipoFactor="Tasa"', replacement)))
            self.assertFalse([name for name in facts.fields if name.endswith(".tax_rate")])
            literal = facts.fields["raw.xml./Comprobante/Impuestos[1]/Traslados[1]/Traslado[1]/@TasaOCuota"][0]
            self.assertEqual(literal.value, "0.160000")

    async def test_discounted_subtotal_is_preserved_without_inventing_net(self):
        for discount in ("10.00", "0.001", "invalid"):
            document = self.parse(CFDI.replace('SubTotal="100.00"', f'SubTotal="100.00" Descuento="{discount}"')
                                  .replace('Importe="100.00"', f'Importe="100.00" Descuento="{discount}"'))
            facts = await XMLDocumentExtractor().extract(document)
            self.assertNotIn("net", facts.fields)
            self.assertNotIn("line.1.net", facts.fields)
            self.assertEqual(facts.fields["discount"][0].value, discount)
            self.assertEqual(facts.fields["raw.xml./Comprobante/@SubTotal"][0].value, "100.00")
        zero = await XMLDocumentExtractor().extract(self.parse(CFDI.replace('SubTotal="100.00"', 'SubTotal="100.00" Descuento="0.00"')))
        self.assertEqual(zero.fields["net"][0].value, "100.00")

    async def test_every_leaf_and_alias_has_exact_original_evidence(self):
        for xml in (FACTURAE, CFDI):
            document = self.parse(xml)
            before = document.to_dict()
            facts = await XMLDocumentExtractor().extract(document)
            originals = {block.source_field: block for block in document.blocks}
            raw = {key.removeprefix("raw.xml."): candidates[0] for key, candidates in facts.fields.items()
                   if key.startswith("raw.xml.")}
            self.assertEqual(set(raw), set(originals))
            for candidates in facts.fields.values():
                for fact in candidates:
                    block = originals[fact.evidence.field]
                    self.assertEqual(fact.value, block.text)
                    self.assertEqual(fact.evidence.quote, block.text)
                    self.assertEqual(fact.evidence.document, document.path)
            self.assertEqual(document.to_dict(), before)
            repeated = await XMLDocumentExtractor().extract(replace(document, blocks=tuple(reversed(document.blocks))))
            self.assertEqual(repeated.to_dict(), facts.to_dict())

    async def test_filename_does_not_classify_or_merge_different_attachments(self):
        one = await XMLDocumentExtractor().extract(self.parse(CFDI, "NOT_INVOICE.xml"))
        other = await XMLDocumentExtractor().extract(self.parse(CFDI.replace('Total="105.33"', 'Total="999.00"'), "INVOICE.xml"))
        self.assertEqual(classify_document(one).document_type, "INVOICE")
        self.assertEqual(one.fields["payable"][0].value, "105.33")
        self.assertEqual(other.fields["payable"][0].value, "999.00")
        self.assertNotEqual(one.source_sha256, other.source_sha256)

    async def test_unsupported_documents_and_invoice_batches_abstain(self):
        invoice = "<Invoice><InvoiceHeader><InvoiceNumber>SECOND</InvoiceNumber></InvoiceHeader></Invoice>"
        examples = [FACTURAE.replace("3.2.2", "3.2.1"), CFDI.replace('Version="4.0"', 'Version="3.3"'),
                    FACTURAE.replace("</Invoices>", invoice + "</Invoices>"), "<Unknown><Total>1</Total></Unknown>"]
        for xml in examples:
            with self.subTest(xml=xml[:30]), self.assertRaises(XMLExtractionError):
                await XMLDocumentExtractor().extract(self.parse(xml))
        document = self.parse(CFDI)
        for changed in (replace(document, media_type="application/pdf"), replace(document, blocks=()),
                        replace(document, blocks=(ParsedBlock("leaf", "value"),)),
                        replace(document, blocks=(*document.blocks, replace(document.blocks[0], id="duplicate")))):
            with self.assertRaises(XMLExtractionError):
                await XMLDocumentExtractor().extract(changed)

    @unittest.skipUnless(os.environ.get("KALMORA_PHASE_ERP"), "original ERP not configured")
    async def test_original_xml_attachments_are_extracted_without_provider_or_golden(self):
        phase = Path(os.environ["KALMORA_PHASE_ERP"]).parent
        router = DocumentRouter(phase)
        formats = {}
        count = 0
        for path in sorted((phase / "inbox/ap").rglob("*.xml")):
            relative = path.relative_to(phase).as_posix()
            document = router.parse(relative)
            facts = await XMLDocumentExtractor().extract(document)
            originals = {block.source_field: block.text for block in document.blocks}
            correction = "/Facturae/Invoices[1]/Invoice[1]/InvoiceHeader[1]/Corrective[1]/InvoiceNumber[1]"
            if correction in originals:
                self.assertEqual(facts.fields["corrective.document_number"][0].value, originals[correction])
            for candidates in facts.fields.values():
                for fact in candidates:
                    self.assertEqual((fact.value, fact.evidence.quote, fact.evidence.document),
                                     (originals[fact.evidence.field], originals[fact.evidence.field], relative))
            for name in ("supplier_tax_id", "recipient_tax_id", "document_number", "document_date", "currency", "net", "payable"):
                self.assertIn(name, facts.fields, (relative, name))
            normalized = normalize_document_facts(facts)
            self.assertFalse([d for d in normalized.diagnostics if d.code == "INVALID_OR_AMBIGUOUS"], relative)
            version = "cfdi" if "raw.cfdi_type" in facts.fields else "facturae"
            formats[version] = formats.get(version, 0) + 1
            count += 1
        self.assertGreater(count, 0)
        self.assertEqual(set(formats), {"facturae", "cfdi"})


if __name__ == "__main__":
    unittest.main()
