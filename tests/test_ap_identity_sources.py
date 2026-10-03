import hashlib
import unittest

from kalmora.ap_identity_sources import resolve_ap_identity
from kalmora.documents.contracts import ResolutionResult
from kalmora.facts import DocumentFacts, Evidence, Fact


class Phase:
    """Minimal PhaseData stand-in: masters only, no golden."""
    def __init__(self, vendors):
        self.companies = [dict(code="1100", tax_id="A12359962"), dict(code="1200", tax_id="B60331798"),
                          dict(code="1910", tax_id="U54740005")]
        self.tables = {"vendors": vendors,
                       "purchase_orders": [dict(id="4500000001", company="1100", vendor="V1")]}

    def table(self, name):
        return self.tables[name]

    def get(self, table, identity):
        rows = [row for row in self.tables[table] if row["id"] == identity]
        if not rows:
            raise KeyError(identity)
        return rows[0]


VENDORS = [dict(id="V1", tax_id="A58455355", email="facturacion@v1.es", companies=["1100", "1910"]),
           dict(id="V2", tax_id="A22905052", email="facturacion@v2.es", companies=["1200"])]


def document(**fields):
    return DocumentFacts(hashlib.sha256(repr(fields).encode()).hexdigest(), "synthetic-v1",
                         {key: [Fact(value, Evidence("factura.pdf", key, page=1, quote=str(value)))]
                          for key, value in fields.items()})


MESSAGE = {"doc_id": "API1", "channel": "email", "from": "facturacion@v1.es"}


class IdentitySourcesTests(unittest.TestCase):
    def resolve(self, vendors=VENDORS, message=MESSAGE, semantic=None, **fields):
        return resolve_ap_identity([document(**fields)], message, Phase(vendors), semantic)

    def test_exact_supplier_and_recipient_with_evidence(self):
        result = self.resolve(supplier_tax_id="A58455355", recipient_tax_id="A12359962")
        self.assertEqual((result.company, result.vendor_id), ("1100", "V1"))
        self.assertNotIn("WRONG_ADDRESSEE", result.diagnostics)
        self.assertIn(Evidence("factura.pdf", "supplier_tax_id", page=1, quote="A58455355"), result.evidence)

    def test_ute_recipient_on_construction_po_is_wrong_addressee(self):
        result = self.resolve(supplier_tax_id="A58455355", recipient_tax_id="U54740005",
                              po_reference="4500000001")
        self.assertEqual((result.company, result.vendor_id), ("1100", "V1"))
        self.assertIn("COMPANY_FROM_PO", result.diagnostics)
        self.assertIn("WRONG_ADDRESSEE", result.diagnostics)
        same = self.resolve(supplier_tax_id="A58455355", recipient_tax_id="U54740005")
        self.assertEqual(same.company, "1910")
        self.assertNotIn("WRONG_ADDRESSEE", same.diagnostics)

    def test_recipient_outside_single_vendor_affiliation_is_wrong_addressee(self):
        result = self.resolve(supplier_tax_id="A22905052", recipient_tax_id="A12359962")
        self.assertEqual((result.company, result.vendor_id), ("1200", "V2"))
        self.assertIn("WRONG_ADDRESSEE", result.diagnostics)

    def test_vendor_not_in_master_keeps_recipient_company(self):
        result = self.resolve(supplier_tax_id="B99999999", recipient_tax_id="B60331798")
        self.assertEqual((result.company, result.vendor_id), ("1200", None))
        self.assertIn("VENDOR_NOT_IN_MASTER", result.diagnostics)

    def test_exact_sender_domain_only_without_observed_tax_id(self):
        self.assertEqual(self.resolve(recipient_tax_id="A12359962").vendor_id, "V1")
        lookalike = dict(MESSAGE, **{"from": "facturacion@v1-es.com"})
        self.assertIsNone(self.resolve(message=lookalike, recipient_tax_id="A12359962").vendor_id)

    def test_ambiguous_supplier_accepts_only_selected_master_candidate(self):
        shared = VENDORS + [dict(id="V3", tax_id="A58455355", companies=["1100"])]
        cases = {None: None,
                 ResolutionResult("AMBIGUOUS", (), (), "two candidates"): None,
                 ResolutionResult("SELECTED", ("V2",), (), "outside allowed set"): None,
                 ResolutionResult("SELECTED", ("V3",), (), "proof"): "V3"}
        for semantic, expected in cases.items():
            with self.subTest(semantic=semantic):
                result = self.resolve(shared, semantic=semantic, supplier_tax_id="A58455355",
                                      recipient_tax_id="A12359962")
                self.assertEqual(result.identity.supplier.status, "AMBIGUOUS")
                self.assertEqual(result.vendor_id, expected)


if __name__ == "__main__":
    unittest.main()
