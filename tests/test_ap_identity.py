import unittest

from kalmora.ap_identity import IdentityCatalog, normalize_tax_identifier
from kalmora.facts import Evidence, Fact


def facts(*values):
    return [Fact(v, Evidence(f"D{i}", "tax_id", quote=str(v))) for i, v in enumerate(values)]


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.vendors = [dict(id="V1", tax_id="B12345678", vat_id="ESB12345678", companies=["1100", "1910"]),
                        dict(id="V2", tax_id="RFC123456AAA", companies=["3100"])]
        self.companies = [dict(code="1100", tax_id="A11111111", vat_id="ESA11111111"),
                          dict(code="1910", tax_id="U22222222"), dict(code="3100", tax_id="KAL123456AAA")]
        self.catalog = IdentityCatalog(vendors=self.vendors, companies=self.companies)

    def resolve(self, supplier=None, recipient=None, expected="1100"):
        return self.catalog.resolve(supplier_tax_ids=supplier, recipient_tax_ids=recipient,
                                    expected_company=expected)

    def test_exact_tax_and_master_vat_aliases_with_evidence(self):
        result = self.resolve(facts("b-123 456 78", "ESB12345678"), facts("ESA11111111"))
        self.assertEqual(result.supplier.identity, "V1")
        self.assertEqual(result.recipient.identity, "1100")
        self.assertFalse(result.wrong_addressee)
        self.assertTrue(result.vendor_enabled_for_company)
        self.assertTrue(any(e.document == "erp/vendors.jsonl" for e in result.supplier.evidence))

    def test_ute_and_construction_are_distinct(self):
        wrong = self.resolve(facts("B12345678"), facts("A11111111"), expected="1910")
        self.assertTrue(wrong.wrong_addressee)
        correct = self.resolve(facts("B12345678"), facts("U22222222"), expected="1910")
        self.assertFalse(correct.wrong_addressee)
        self.assertEqual(correct.recipient.identity, "1910")

    def test_unknown_absent_and_nonexistent_are_distinct(self):
        self.assertEqual(self.resolve(None).supplier.status, "UNKNOWN")
        self.assertEqual(self.resolve([]).supplier.status, "MISSING")
        self.assertEqual(self.resolve(facts(None)).supplier.status, "MISSING")
        self.assertEqual(self.resolve(facts("NONEXISTENT1")).supplier.status, "NOT_FOUND")
        self.assertIsNone(self.resolve(facts("B12345678"), []).wrong_addressee)

    def test_conflicting_document_facts_are_not_overwritten(self):
        result = self.resolve(facts("B12345678", "RFC123456AAA"), facts("A11111111", "U22222222"))
        self.assertEqual((result.supplier.status, result.recipient.status), ("CONFLICT", "CONFLICT"))
        self.assertIsNone(result.supplier.identity)
        self.assertEqual(result.supplier.candidates, ("V1", "V2"))
        self.assertEqual(self.resolve(facts("B12345678", None)).supplier.status, "CONFLICT")

    def test_ambiguous_master_ids_and_company_affiliation(self):
        catalog = IdentityCatalog(vendors=self.vendors + [dict(id="V3", tax_id="B12345678")], companies=self.companies)
        result = catalog.resolve(supplier_tax_ids=facts("B12345678"), recipient_tax_ids=[], expected_company="1100")
        self.assertEqual(result.supplier.status, "AMBIGUOUS")
        self.assertFalse(self.resolve(facts("RFC123456AAA")).vendor_enabled_for_company)
        self.vendors[0]["companies"].clear()  # input mutation cannot change the snapshot
        self.assertTrue(self.resolve(facts("B12345678")).vendor_enabled_for_company)

    def test_prefix_is_never_guessed_and_malformed_master_fails(self):
        self.assertEqual(self.resolve(facts("123456AAA"), expected="3100").supplier.status, "NOT_FOUND")
        self.assertEqual(self.resolve(facts("RFC123456AAA"), expected="3100").supplier.identity, "V2")
        with self.assertRaises(ValueError):
            IdentityCatalog(vendors=self.vendors * 2, companies=self.companies)
        with self.assertRaises(ValueError):
            self.resolve(facts("B12345678"), expected="9999")
        for invalid in ("", "B123@456", "Α12345678"):
            with self.assertRaises(ValueError):
                normalize_tax_identifier(invalid)


if __name__ == "__main__":
    unittest.main()
