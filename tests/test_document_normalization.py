import unittest
from decimal import Decimal, localcontext

from kalmora.documents.normalization import normalize_document_facts
from kalmora.facts import DocumentFacts, Evidence, Fact


class NormalizationTests(unittest.TestCase):
    def test_literal_raw_values_and_normalized_identity_survive_a_second_pass(self):
        original = '  Original XML leaf with accents: á  '
        result = self.normalize({'raw.xml./Invoice/Name': original, 'net': '100,00',
                                 'line.1.unit': 'kg', 'unit': 'unrelated header'})
        self.assertEqual(result.facts.fields['raw.xml./Invoice/Name'][0].value, original)
        self.assertEqual(result.facts.fields['line.1.uom'][0].value, 'kg')
        self.assertEqual(result.facts.fields['unit'][0].value, 'unrelated header')
        self.assertEqual(normalize_document_facts(result.facts).facts, result.facts)

    def test_diagnostics_do_not_depend_on_field_order(self):
        def fact(value):
            return [Fact(value, Evidence("doc.pdf", "page.1", 1, value))]
        fields = {"period_start": fact("01/06/2026"), "lines": [Fact([{"quantity": "2.520"}],
                                                                     Evidence("doc.pdf", "page.1", 1, "2.520"))]}
        forward = normalize_document_facts(DocumentFacts("a" * 64, "x", dict(fields)))
        backward = normalize_document_facts(DocumentFacts("a" * 64, "x", dict(reversed(list(fields.items())))))
        self.assertEqual(len(forward.diagnostics), 2)
        self.assertEqual(forward.diagnostics, backward.diagnostics)

    def test_scaling_retains_digits_in_a_low_precision_decimal_context(self):
        with localcontext() as context:
            context.prec = 2
            result = self.normalize({'net': '(123456789.12)', 'taxable_base': '123456789.12'})
        self.assertEqual(result.facts.fields['net_cents'][0].value, -12345678912)
        self.assertEqual(result.facts.fields['taxable_base_cents'][0].value, 12345678912)

    def test_unit_alias_conflict_keeps_both_original_proofs(self):
        source = DocumentFacts('a' * 64, 'test', {
            'line.1.unit': [Fact('kg', Evidence('invoice.pdf', 'p1', quote='kg'))],
            'line.1.uom': [Fact('t', Evidence('invoice.pdf', 'p2', quote='t'))],
        })
        result = normalize_document_facts(source)
        self.assertEqual({fact.value for fact in result.conflicts['line.1.uom']}, {'kg', 't'})
        self.assertEqual({fact.evidence.field for fact in result.conflicts['line.1.uom']}, {'p1', 'p2'})

    def normalize(self, fields, source="invoice.pdf", locator="block:1"):
        evidence = Evidence(source, locator, quote="source")
        return normalize_document_facts(DocumentFacts("a" * 64, "test", {
            key: [Fact(value, evidence)] for key, value in fields.items()
        }))

    def test_exact_units_credit_sign_and_raw(self):
        result = self.normalize({"net": "-1.234,56", "tax": "(2.50)",
            "quantity": "0.125", "unit_price": "2.1234", "tax_rate": "21%"})
        self.assertEqual({key: facts[0].value for key, facts in result.facts.fields.items()},
            {"net_cents": -123456, "tax_cents": -250, "quantity_milli": 125,
             "unit_price_e4": 21234, "tax_rate_e4": 2100})
        self.assertEqual(result.raw.fields["net"][0].value, "-1.234,56")
        self.assertEqual(result.diagnostics, ())

    def test_ambiguity_invalid_types_and_precision(self):
        for value in ("1,234", "1.234", True, 1.23, Decimal("NaN"), "1 2", "1,23.45"):
            with self.subTest(value=value):
                result = self.normalize({"net": value})
                self.assertFalse(result.facts.fields)
                self.assertTrue(result.diagnostics)
        self.assertFalse(self.normalize({"quantity": "0.0001"}).facts.fields)
        self.assertFalse(self.normalize({"net": "21%"}).facts.fields)
        self.assertFalse(self.normalize({"future": {"nested": [1.2]}}).facts.fields)
        result = self.normalize({"net": "0.005"})
        self.assertEqual(result.facts.fields["net_cents"][0].value, 1)
        self.assertEqual(result.diagnostics[0].code, "ROUNDED_HALF_UP")
        xml = self.normalize({"net": "1.234"}, "invoice.xml", "/Invoice/Amount")
        self.assertEqual(xml.facts.fields["net_cents"][0].value, 123)

    def test_dates_currency_and_explicit_absence(self):
        result = self.normalize({"document_date": "13/02/2026", "currency": "eur", "tax": None})
        self.assertEqual(result.facts.fields["document_date"][0].value, "2026-02-13")
        self.assertIsNone(result.facts.fields["tax_cents"][0].value)
        for value, expected in (("30 de junio de 2026", "2026-06-30"), ("7 de julho de 2026", "2026-07-07")):
            self.assertEqual(self.normalize({"document_date": value}).facts.fields["document_date"][0].value, expected)
        for value in ("03/04/2026", "2026-02-30", "30 de juny de 2026"):
            self.assertFalse(self.normalize({"document_date": value}).facts.fields)
        self.assertFalse(self.normalize({"currency": "$"}).facts.fields)

    def test_notice_validity_dates_and_ibans_normalize(self):
        result = self.normalize({"certificate_valid_from": "27/06/2026",
                                 "certificate_tax_valid_until": "27/06/2027", "new_iban": "es12 3456"})
        self.assertEqual({key: facts[0].value for key, facts in result.facts.fields.items()},
                         {"certificate_valid_from": "2026-06-27",
                          "certificate_tax_valid_until": "2027-06-27", "new_iban": "ES123456"})

    def test_alias_conflicts_and_all_line_namespaces(self):
        result = self.normalize({"invoice_number": "A", "document_number": "B",
            "line.1.amount": "1", "lines.2.amount": "2", "lines[3].amount": "3",
            "lines[0].amount": "9", "buyer_tax_id": "es-123"})
        self.assertIn("document_number", result.conflicts)
        self.assertEqual(len(result.facts.fields["document_number"]), 2)
        self.assertEqual(result.facts.fields["recipient_tax_id"][0].value, "ES123")
        self.assertEqual(result.facts.fields["line.3.amount_cents"][0].value, 300)
        self.assertNotIn("line.0.amount_cents", result.facts.fields)
        nested = self.normalize({"lines": [{"quantity": "2"}, {"amount": "3"}]})
        self.assertEqual(nested.facts.fields["line.1.quantity_milli"][0].value, 2000)
        self.assertEqual(nested.facts.fields["line.2.amount_cents"][0].value, 300)

    def test_attachments_never_merge_and_evidence_retained(self):
        source = DocumentFacts("a" * 64, "test", {"net": [
            Fact("1", Evidence("a.pdf", "block1")), Fact("2", Evidence("a.xml", "/net"))]})
        result = normalize_document_facts(source)
        self.assertFalse(result.facts.fields)
        self.assertEqual(result.diagnostics[0].code, "MIXED_SOURCE")
        result = self.normalize({"net": "2"})
        self.assertEqual(result.raw.fields["net"][0].evidence,
                         result.facts.fields["net_cents"][0].evidence)


if __name__ == "__main__":
    unittest.main()
