"""Source interpretation connects to typed AP facts without month-specific guesses."""
from dataclasses import replace
from datetime import date
from decimal import Decimal, localcontext
import unittest

from kalmora.ap_document_bridge import APDocumentBridge, APSourceView
from kalmora.ap_identity import IdentityCatalog
from kalmora.documents.classification import DocumentClassification
from kalmora.documents.ap_sources import APAttachment, APMessage, APTaskSources
from kalmora.documents.contracts import ParsedDocument
from kalmora.documents.normalization import normalize_document_facts
from kalmora.facts import DocumentFacts, Evidence, Fact


class APDocumentBridgeTests(unittest.TestCase):
    def normalize(self, fields, path="inbox/ap/OTHER/document.pdf", sha="a" * 64):
        return normalize_document_facts(DocumentFacts(sha, "synthetic-v1", {
            name: values if isinstance(values, list) and all(isinstance(v, Fact) for v in values)
            else [Fact(values, Evidence(path, "block:" + name, 1, str(values)))]
            for name, values in fields.items()}))

    def source(self, fields, path="inbox/ap/OTHER/document.pdf", **kwargs):
        return APSourceView.from_normalized(self.normalize(fields, path), source_path=path, **kwargs)

    def test_normalized_header_identity_connects_to_existing_catalog(self):
        source = self.source(dict(supplier_tax_id="tax-49", recipient_tax_id="tax-17",
            invoice_number="OTHER-902", invoice_date="2034-02-13", currency="eur",
            net="10,00", tax="2,10", gross="12,10", document_type_hint="Invoice"))
        bridge = APDocumentBridge("opaque-task", (source,))
        header = bridge.header
        self.assertEqual((header.issuer_tax_id.value, header.recipient_tax_id.value), ("TAX49", "TAX17"))
        self.assertEqual((header.invoice_number.value, header.invoice_date.date_value),
                         ("OTHER-902", date(2034, 2, 13)))
        self.assertEqual((header.currency.value, header.net_cents.value, header.tax_cents.value,
                          header.gross_cents.value), ("EUR", 1000, 210, 1210))
        self.assertEqual(bridge.field("invoice_number"), bridge.field("document_number"))
        self.assertEqual(source.raw.field("invoice_number").value, "OTHER-902")
        self.assertEqual(source.raw.field("document_number").status, "UNKNOWN")
        identity = IdentityCatalog(vendors=[dict(id="vendor-49", tax_id="TAX49", companies=["company-17"])],
            companies=[dict(code="company-17", tax_id="TAX17")]).resolve(
            supplier_tax_ids=header.issuer_tax_id.candidates,
            recipient_tax_ids=header.recipient_tax_id.candidates, expected_company="company-17")
        self.assertEqual((identity.supplier.identity, identity.recipient.identity), ("vendor-49", "company-17"))
        self.assertEqual(bridge.classification.document_type, "INVOICE")

    def test_attachment_consensus_retains_each_proof_and_preserves_disagreement(self):
        pdf = self.source(dict(invoice_number="N-1", currency="EUR", gross="121,00"))
        xml = self.source(dict(invoice_number="N-1", currency="EUR", gross="122.00"),
                          "inbox/ap/OTHER/document.xml")
        bridge = APDocumentBridge("OTHER", (pdf, xml))
        self.assertEqual((bridge.header.invoice_number.status, len(bridge.header.invoice_number.evidence)),
                         ("RESOLVED", 2))
        self.assertEqual((bridge.header.gross_cents.status, bridge.header.gross_cents.value), ("CONFLICT", None))
        self.assertEqual([fact.value for fact in bridge.header.gross_cents.candidates], [12100, 12200])
        self.assertEqual((pdf.header.gross_cents.value, xml.header.gross_cents.value), (12100, 12200))

    def test_missing_fact_is_unknown_but_evidenced_absence_is_missing(self):
        absent = self.source(dict(recipient_tax_id=None))
        empty = self.source({}, "inbox/ap/OTHER/empty.pdf")
        self.assertEqual((empty.header.recipient_tax_id.status, empty.header.recipient_tax_id.evidence),
                         ("UNKNOWN", ()))
        self.assertEqual((absent.header.recipient_tax_id.status, len(absent.header.recipient_tax_id.evidence)),
                         ("MISSING", 1))
        known = self.source(dict(recipient_tax_id="TAX-OTHER"), "inbox/ap/OTHER/known.pdf")
        self.assertEqual(APDocumentBridge("OTHER", (absent, known)).header.recipient_tax_id.status, "CONFLICT")
        self.assertEqual(APDocumentBridge("OTHER", (empty, known)).header.recipient_tax_id.value, "TAXOTHER")

    def test_flat_rows_nested_rows_and_extensions_keep_source_index_and_units(self):
        source = self.source({"line.1.quantity": "0.125", "line.1.uom": "tonnes",
            "line.1.unit_price": "12.3456", "line.1.amount": "1.54",
            "line.1.po_reference": "PO-OTHER", "line.1.po_item": 30,
            "line.1.tax.charge.1.tax_rate": "21%", "line.1.raw.S/Ref.": "literal ref",
            "line.2.quantity": "-1", "line.2.net": "-10", "line.2.receiver_transaction_reference": "ORDER-OR-CONTRACT"})
        first, second = source.lines
        self.assertEqual((first.quantity_milli.value, first.quantity.value, first.uom.value),
                         (125, Decimal("0.125"), "tonnes"))
        self.assertEqual((first.unit_price_e4.value, first.unit_price_cents.value, first.amount_cents.value),
                         (123456, Decimal("1234.56"), 154))
        self.assertEqual(first.field("tax.charge.1.tax_rate_e4").value, 2100)
        self.assertEqual(first.field("raw.S/Ref.").value, "literal ref")
        self.assertEqual(first.references["po_item"].value, 30)
        self.assertEqual(second.references["receiver_transaction_reference"].value, "ORDER-OR-CONTRACT")
        self.assertEqual(second.field("po_reference").status, "UNKNOWN")
        self.assertEqual((second.quantity_milli.value, second.net_cents.value, second.uom.status),
                         (-1000, -1000, "UNKNOWN"))
        nested = self.source({"lines": [{"description": "actual row", "quantity": 2}]})
        self.assertEqual((len(nested.lines), nested.lines[0].quantity_milli.value), (1, 2000))

    def test_rows_in_different_attachments_never_merge_or_sum_by_position(self):
        fields = {"line.1.quantity": "2", "line.1.unit_price": "3.00", "line.1.amount": "6.00"}
        pdf = self.source(fields)
        xml = self.source(fields, "inbox/ap/OTHER/document.xml")
        bridge = APDocumentBridge("OTHER", (pdf, xml))
        self.assertEqual(len(bridge.lines), 2)
        self.assertEqual(len({line.line_id for line in bridge.lines}), 2)
        self.assertEqual([line.quantity_milli.value for line in bridge.lines], [2000, 2000])
        self.assertEqual(bridge.field("line.1.quantity_milli").diagnostics, ("ATTACHMENT_SCOPE_REQUIRED",))
        self.assertNotIn("line.1.quantity_milli", bridge.facts.fields)

    def test_exact_unit_views_do_not_round_under_decimal_context(self):
        source = self.source({"line.1.unit_price_e4": 123456789012345678901234567890,
                              "line.1.quantity_milli": 123456789012345678901234567890})
        with localcontext() as context:
            context.prec = 4
            self.assertEqual(str(source.lines[0].unit_price_cents.value), "1234567890123456789012345678.90")
            self.assertEqual(str(source.lines[0].quantity.value), "123456789012345678901234567.890")

    def test_ambiguous_dates_invalid_numbers_and_gaps_stay_visible(self):
        source = self.source({"invoice_date": "03/04/2034", "currency": "$",
                              "line.3.quantity": "0.0001", "line.3.description": "third observed row"})
        self.assertEqual((source.header.invoice_date.status, source.header.currency.status), ("UNKNOWN", "UNKNOWN"))
        self.assertEqual((source.lines[0].index, source.lines[0].quantity_milli.status), (3, "UNKNOWN"))
        self.assertIn("LINE_INDEX_GAP", source.diagnostics)
        self.assertTrue(any(item.startswith("INVALID_OR_AMBIGUOUS") for item in source.diagnostics))
        self.assertTrue(any(item.evidence and item.message for item in source.normalization_diagnostics))
        normalized = self.normalize({"line.1.quantity_milli": 3})
        normalized.facts.fields["line.1.quantity_milli"] = [Fact(True, Evidence("inbox/ap/OTHER/document.pdf", "quantity"))]
        malformed = APSourceView.from_normalized(normalized, source_path="inbox/ap/OTHER/document.pdf")
        self.assertEqual(malformed.lines[0].quantity_milli.status, "INVALID")

    def test_classification_keeps_literal_hints_and_never_reads_invoice_mentions(self):
        statement = self.source({"document_type_hint": "Vendor statement", "raw.body": "invoice INV-1 overdue"})
        self.assertEqual(statement.classification.document_type, "VENDOR_STATEMENT")
        self.assertEqual(statement.raw.field("raw.body").value, "invoice INV-1 overdue")
        unknown = self.source({"raw.invoice_class": "CO"}, "inbox/ap/OTHER/copy.xml")
        self.assertEqual(unknown.classification.status, "UNKNOWN")
        self.assertEqual(APDocumentBridge("OTHER", (statement, unknown)).classification.status, "UNKNOWN")
        invoice = self.source({"document_type_hint": "Invoice"}, "inbox/ap/OTHER/invoice.pdf")
        self.assertEqual(APDocumentBridge("OTHER", (statement, invoice)).classification.status, "CONFLICT")
        self.assertEqual(APDocumentBridge("OTHER", ()).classification.status, "UNKNOWN")

    def test_explicit_format_classification_keeps_original_class_evidence(self):
        path = "inbox/ap/OTHER/invoice.xml"
        normalized = self.normalize({"raw.invoice_class": "CO"}, path)
        proof = normalized.raw.fields["raw.invoice_class"][0]
        supplied = DocumentClassification("INVOICE", "CLASSIFIED", (proof,), (), "format-classifier-test")
        source = APSourceView.from_normalized(normalized, source_path=path, classification=supplied)
        self.assertEqual((source.classification.document_type, source.classification.evidence[0].value), ("INVOICE", "CO"))
        foreign = DocumentClassification("INVOICE", "CLASSIFIED", (
            Fact("CO", Evidence("inbox/ap/OTHER/other.xml", "class")),), ())
        with self.assertRaises(ValueError):
            APSourceView.from_normalized(normalized, source_path=path, classification=foreign)
        with self.assertRaises(ValueError):
            APSourceView.from_normalized(normalized, source_path=path, classification=DocumentClassification(
                "INVOICE", "CLASSIFIED", (), ()))

    def test_source_and_original_bytes_must_match_and_duplicate_attachment_fails(self):
        normalized = self.normalize({"gross": "1.00"})
        with self.assertRaises(ValueError):
            APSourceView.from_normalized(normalized, source_path="golden/invoice.pdf")
        with self.assertRaises(ValueError):
            APSourceView.from_normalized(normalized, source_path="inbox/ap/OTHER/other.pdf")
        wrong_sha = replace(normalized, facts=DocumentFacts("b" * 64, "v", normalized.facts.fields))
        with self.assertRaises(ValueError):
            APSourceView.from_normalized(wrong_sha, source_path="inbox/ap/OTHER/document.pdf")
        source = APSourceView.from_normalized(normalized, source_path="inbox/ap/OTHER/document.pdf")
        with self.assertRaises(ValueError):
            APDocumentBridge("OTHER", (source, source))
        same_bytes_other_path = self.source({"gross": "1.00"}, "inbox/ap/OTHER/copy.pdf")
        self.assertEqual(len(APDocumentBridge("OTHER", (source, same_bytes_other_path)).sources), 2)

    def test_fact_snapshots_are_not_changed_by_input_or_exported_mapping_mutation(self):
        normalized = self.normalize({"raw.group": {"value": [1]}, "gross": "1.00"})
        source = APSourceView.from_normalized(normalized, source_path="inbox/ap/OTHER/document.pdf")
        normalized.facts.fields["gross_cents"] = [Fact(9999, Evidence(source.source_path, "gross"))]
        exported = source.facts.fields
        exported["raw.group"][0].value["value"].append(2)
        self.assertEqual(source.header.gross_cents.value, 100)
        self.assertEqual(source.field("raw.group").value, {"value": [1]})

    def test_existing_task_contract_retains_extraction_failures_and_source_roles(self):
        invoice_path = "inbox/ap/OTHER/invoice.pdf"
        notice_path = "inbox/ap/OTHER/notice.pdf"
        normalized = self.normalize({"document_type_hint": "Invoice", "gross": "100.00"}, invoice_path)
        notice = self.normalize({"document_type_hint": "Bank details change"}, notice_path)
        task = APTaskSources("OTHER", APMessage("inbox/ap/OTHER/message.json", "c" * 64,
            None, None, None, None, None, None, (), {}), (
            APAttachment(invoice_path, ParsedDocument(invoice_path, "a" * 64, "application/pdf", "test", ()),
                         normalized=normalized, unknowns=({"field": "iban", "status": "MISSING"},)),
            APAttachment(notice_path, None, normalized=notice),
            APAttachment("inbox/ap/OTHER/failure.png", None, error="MISSING_CAPTURE")))
        bridge = APDocumentBridge.from_task_sources(task)
        self.assertEqual([source.source_path for source in bridge.financial_sources], [invoice_path])
        self.assertEqual([source.source_path for source in bridge.notice_sources], [notice_path])
        self.assertEqual(bridge.financial_sources[0].header.invoice_number.status, "UNKNOWN")
        self.assertEqual(bridge.financial_sources[0].extraction_unknowns[0]["status"], "MISSING")
        self.assertEqual(bridge.financial_sources[0].field("iban").status, "UNKNOWN")
        self.assertEqual(bridge.source_issues[0].diagnostic, "MISSING_CAPTURE")
        self.assertEqual(bridge.classification.status, "CONFLICT")
        invoice_only = APDocumentBridge("OTHER", bridge.financial_sources, source_issues=bridge.source_issues)
        self.assertEqual(invoice_only.classification.status, "UNKNOWN")
        mismatched = replace(task, attachments=(replace(task.attachments[0], document=ParsedDocument(
            invoice_path, "f" * 64, "application/pdf", "test", ())),))
        with self.assertRaises(ValueError):
            APDocumentBridge.from_task_sources(mismatched)
        wrong_raw = replace(task, attachments=(replace(task.attachments[0],
            facts=DocumentFacts("a" * 64, "synthetic-v1", {})),))
        with self.assertRaises(ValueError):
            APDocumentBridge.from_task_sources(wrong_raw)


if __name__ == "__main__":
    unittest.main()
