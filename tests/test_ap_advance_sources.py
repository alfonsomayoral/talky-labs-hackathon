from copy import deepcopy
from dataclasses import replace
import unittest

from kalmora.ap_advance_sources import AdvanceApproval, resolve_advance_sources
from kalmora.ap_journal import build_down_payment_request
from kalmora.facts import Evidence, Fact
from kalmora.money import RateTable


class AdvanceSourceTests(unittest.TestCase):
    def setUp(self):
        self.po = {"id": "P1", "company": "1100", "currency": "USD", "vendor": "V1",
                   "created_on": "2026-01-01", "items": [{"item": 10}]}
        self.vendor = {"id": "V1", "tax_id": "DE123", "country": "DE", "companies": ["1100"], "currency": "EUR"}
        self.companies = [{"code": "1100", "tax_id": "ES1100", "country": "ES"},
                          {"code": "1910", "tax_id": "ES1910", "country": "ES"}]
        self.reference = Fact("P1", Evidence("request.pdf", "po", page=1))
        self.approval = AdvanceApproval(Fact("P1", Evidence("approval.xml", "po")),
                                        Fact(True, Evidence("approval.xml", "approved")))

    def resolve(self, **changes):
        options = dict(company="1100", currency="USD", invoice_date="2026-07-01",
            po_reference=self.reference, approval=self.approval, purchase_orders=[self.po],
            vendors=[self.vendor], companies=self.companies)
        options.update(changes)
        return resolve_advance_sources(**options)

    def test_exact_documentary_po_approval_and_master_prove_partner_on_both_lines(self):
        before = deepcopy((self.po, self.vendor))
        result = self.resolve(supplier_tax_ids=[Fact("DE-123", Evidence("request.pdf", "supplier_tax_id"))],
                              recipient_tax_ids=[Fact("ES1100", Evidence("request.pdf", "recipient_tax_id"))])
        self.assertEqual(result.status, "RESOLVED")
        self.assertEqual(result.order.vendor, "V1")
        self.assertTrue(any(e.document == "erp/purchase_orders.jsonl" and e.field.endswith("vendor") for e in result.evidence))
        rates = RateTable([{"currency": "USD", "date": "2026-07-01", "rate": "1.2"}])
        for doc_id, amount, day in (("NEW", 12000, "2026-07-01"), ("REUSED", 24000, "2026-07-02")):
            journal = build_down_payment_request(company=result.order.company, vendor=result.order.vendor,
                vendor_country=result.vendor_master["country"], vendor_master=result.vendor_master,
                currency=result.order.currency, doc_id=doc_id, invoice_number=f"DEP-{doc_id}",
                invoice_date=day, posting_date=day, amount_doc=amount, decision="POST",
                order=result.order, rates=rates)
            self.assertEqual({line["partner"] for line in journal.journal_entry["lines"]}, {"V1"})
            self.assertEqual({line["account"] for line in journal.journal_entry["lines"]}, {"40700000", "40000000"})
            with self.assertRaises(ValueError):
                build_down_payment_request(company="1100", vendor="V1", vendor_country="DE", vendor_master=result.vendor_master,
                    currency="USD", doc_id=doc_id, invoice_number=f"DEP-{doc_id}", invoice_date=day,
                    posting_date=day, amount_doc=amount, decision="POST", order=result.order, rates=rates, state=journal.state)
        self.assertEqual((self.po, self.vendor), before)
        result.vendor_master["companies"].append("1910")
        self.assertEqual(self.vendor["companies"], ["1100"])

    def test_unresolved_documentary_po_or_approval_never_exposes_postable_inputs(self):
        for fields in (dict(po_reference=None), dict(po_reference=Fact(None, Evidence("request.pdf", "po"))),
                       dict(approval=None), dict(approval=replace(self.approval, approved=Fact(None, Evidence("approval.xml", "approved")))),
                       dict(approval=replace(self.approval, approved=Fact(1, Evidence("approval.xml", "approved")))),
                       dict(approval=replace(self.approval, approved=Fact("true", Evidence("approval.xml", "approved"))))):
            result = self.resolve(**fields)
            self.assertEqual(result.status, "UNKNOWN")
            self.assertIsNone(result.order)
            self.assertIsNone(result.vendor_master)
            self.assertTrue(result.diagnostics)
        self.assertEqual(self.resolve(approval=replace(self.approval, approved=Fact(False, Evidence("approval.xml", "approved")))).status,
                         "NOT_APPROVED")
        observed = Fact("DE123", Evidence("request.pdf", "supplier"))
        result = self.resolve(approval=None, supplier_tax_ids=[observed])
        self.assertIn(observed.evidence, result.evidence)

    def test_approval_and_po_scope_contradictions_do_not_recover_another_po(self):
        for fields in (dict(company="1910"), dict(currency="EUR"), dict(invoice_date="2025-12-31"),
                       dict(approval=replace(self.approval, po_reference=Fact("OTHER", Evidence("approval.xml", "po"))))):
            self.assertEqual(self.resolve(**fields).status, "CONFLICT")
        self.assertEqual(self.resolve(approval=replace(self.approval, approved=Fact(True, Evidence("unrelated.pdf", "approved")))).status,
                         "UNKNOWN")
        self.assertEqual(self.resolve(purchase_orders=[]).status, "NOT_FOUND")
        with self.assertRaises(ValueError):
            self.resolve(purchase_orders=[self.po, self.po])

    def test_master_absence_affiliation_and_foreign_country_are_explicit(self):
        self.assertEqual(self.resolve(vendors=[]).status, "NOT_FOUND")
        cases = [({key: value for key, value in self.vendor.items() if key != "companies"}, "UNKNOWN"),
                 ({**self.vendor, "companies": ["1910"]}, "CONFLICT"),
                 ({**self.vendor, "country": "ZZ"}, "UNKNOWN"),
                 ({**self.vendor, "country": "ES"}, "DOMESTIC")]
        for master, status in cases:
            self.assertEqual(self.resolve(vendors=[master]).status, status)

    def test_observed_tax_identifiers_cannot_be_overridden_by_po(self):
        for field, facts in (("supplier_tax_ids", [Fact("WRONG", Evidence("request.pdf", "supplier"))]),
                             ("recipient_tax_ids", [Fact("ES1910", Evidence("request.pdf", "recipient"))]),
                             ("supplier_tax_ids", [Fact("DE123", Evidence("request.pdf", "supplier")),
                                                   Fact("WRONG", Evidence("request.xml", "supplier"))])):
            self.assertEqual(self.resolve(**{field: facts}).status, "CONFLICT")
        # Missing identifier is distinct from a contradictory observed value.
        self.assertEqual(self.resolve(supplier_tax_ids=[Fact(None, Evidence("request.pdf", "supplier"))]).status, "RESOLVED")
        duplicate_alias = {**self.vendor, "id": "V2"}
        result = self.resolve(vendors=[self.vendor, duplicate_alias], supplier_tax_ids=[Fact("DE123", Evidence("request.pdf", "supplier"))])
        self.assertEqual(result.status, "CONFLICT")
        self.assertEqual(result.identity.supplier.status, "AMBIGUOUS")

    def test_no_document_id_amount_or_po_position_special_cases(self):
        for po_id, vendor_id, date_value, items in (("P-NEW", "V-NEW", "2026-06-01", [{"item": 40}, {"item": 10}]),
                                                    ("P1", "V1", "2026-07-01", [{"item": 20}])):
            po = {**self.po, "id": po_id, "vendor": vendor_id, "items": items}
            approval = AdvanceApproval(Fact(po_id, Evidence("other-approval.pdf", "po")),
                                       Fact(True, Evidence("other-approval.pdf", "approved")))
            result = self.resolve(purchase_orders=[po], vendors=[{**self.vendor, "id": vendor_id}],
                po_reference=Fact(po_id, Evidence("new-request.pdf", "po", page=3)), approval=approval, invoice_date=date_value)
            self.assertEqual(result.order.vendor, vendor_id)
            self.assertEqual(result.order.po, po_id)


if __name__ == "__main__":
    unittest.main()
