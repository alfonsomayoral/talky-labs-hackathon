from dataclasses import replace
import unittest
from kalmora.ap_allocation import ConsumptionState, ReceiptUsage
from kalmora.ap_orders import POCatalog, POQuery
from kalmora.facts import Evidence


class OrderResolutionTests(unittest.TestCase):
    def setUp(self):
        self.orders = [dict(id="PO1", company="1100", vendor="V1", currency="EUR", created_on="2026-01-01", project="W1",
                            items=[dict(item=10, uom="ud", material="M1", description="Concrete supply", unit_price=100)])]
        self.receipts = [dict(id="R1", company="1100", vendor="V1", po="PO1", po_item=10, quantity_milli=1000,
                              posting_date="2026-07-01", type="GR", reference="DELIVERY1")]
        self.catalog = POCatalog(orders=self.orders, receipts=self.receipts)
        self.query = POQuery("L1", "1100", "V1", "EUR", 1000, "ud", (Evidence("invoice", "line1"),))

    def resolve(self, **kwargs):
        return self.catalog.resolve(replace(self.query, **kwargs), invoice_date="2026-07-31")

    def test_explicit_reference_and_missing_or_erroneous_reference_recovery(self):
        self.assertEqual(self.resolve(po_reference="PO1", po_item=10).status, "RESOLVED")
        for reference in (None, "OLD_PO"):
            result = self.resolve(po_reference=reference, material="M1")
            self.assertEqual(result.status, "RESOLVED")
            self.assertTrue(result.reference_recovered)
            self.assertEqual(result.selected.order.po, "PO1")
        self.assertEqual(self.resolve(description="  concrete   SUPPLY ").status, "RESOLVED")
        self.assertEqual(self.resolve(receipt_references=("DELIVERY1",)).status, "RESOLVED")

    def test_scope_alone_is_not_confirmation_and_ambiguity_stays_visible(self):
        self.assertEqual(self.resolve().status, "UNCONFIRMED")
        second = dict(self.orders[0], id="PO2")
        catalog = POCatalog(orders=self.orders + [second], receipts=self.receipts)
        result = catalog.resolve(replace(self.query, material="M1"), invoice_date="2026-07-31")
        self.assertEqual((result.status, result.selected), ("AMBIGUOUS", None))

    def test_reference_conflict_does_not_choose_an_alternative(self):
        self.assertEqual(self.resolve(po_reference="PO1", material="M2").status, "CONFLICT")
        self.assertEqual(self.resolve(receipt_references=("MISSING",)).status, "UNKNOWN")
        missing_receipt = self.resolve(po_reference="PO1", receipt_references=("MISSING",))
        self.assertEqual((missing_receipt.status, missing_receipt.selected), ("UNKNOWN", None))
        self.assertEqual(missing_receipt.candidates[0].receipts, ())
        self.assertEqual(missing_receipt.diagnostics, ("UNRESOLVED_RECEIPT:MISSING",))

    def test_valid_order_cannot_be_replaced_to_hide_project_unit_or_item_conflicts(self):
        second = dict(self.orders[0], id="PO2", project="W2")
        catalog = POCatalog(orders=self.orders + [second], receipts=self.receipts)
        for fields in (dict(project="W2"), dict(uom="mes"), dict(po_item=20)):
            result = catalog.resolve(replace(self.query, po_reference="PO1", material="M1", **fields), invoice_date="2026-07-31")
            self.assertEqual((result.status, result.selected), ("CONFLICT", None))

    def test_position_is_a_constraint_even_without_order_number(self):
        self.assertEqual(self.resolve(po_item=20, material="M1").status, "NOT_FOUND")
        second_item = dict(self.orders[0]["items"][0], item=20)
        catalog = POCatalog(orders=[dict(self.orders[0], items=[*self.orders[0]["items"], second_item])], receipts=self.receipts)
        result = catalog.resolve(replace(self.query, po_item=20, material="M1"), invoice_date="2026-07-31")
        self.assertEqual((result.status, result.selected.order.item, result.reference_recovered), ("RESOLVED", 20, True))
        self.assertTrue(self.resolve(po_reference="PO1").reference_recovered)

    def test_all_receipt_references_must_be_reconciled(self):
        other = dict(self.orders[0], id="PO2")
        other_receipt = dict(self.receipts[0], id="R2", po="PO2", reference="DELIVERY2")
        catalog = POCatalog(orders=self.orders + [other], receipts=self.receipts + [other_receipt])
        for refs, expected in ((("DELIVERY1", "DELIVERY2"), "CONFLICT"),
                               (("DELIVERY1", "MISSING"), "UNKNOWN"),
                               (("DELIVERY2", "MISSING"), "CONFLICT")):
            result = catalog.resolve(replace(self.query, po_reference="PO1", receipt_references=refs), invoice_date="2026-07-31")
            self.assertEqual((result.status, result.selected), (expected, None))
            self.assertTrue(all(not c.receipts for c in result.candidates))
        result = catalog.resolve(replace(self.query, receipt_references=("DELIVERY1", "DELIVERY2")), invoice_date="2026-07-31")
        self.assertEqual(result.status, "CONFLICT")

    def test_scope_date_units_and_consumption(self):
        for field, value in (("company", "1910"), ("vendor", "V2"), ("currency", "USD"),
                             ("uom", "mes"), ("project", "W2")):
            self.assertEqual(self.resolve(**{field: value}).status, "NOT_FOUND")
        early = self.catalog.resolve(replace(self.query, po_reference="PO1"), invoice_date="2026-06-30")
        self.assertEqual((early.status, early.selected.available_milli), ("RESOLVED", 0))
        result = self.resolve(po_reference="PO1", quantity_milli=2000)
        self.assertEqual(result.status, "RESOLVED")  # quantity deficit belongs to #44/#49
        state = ConsumptionState((ReceiptUsage(result.selected.order, "R1", 750),))
        used = self.catalog.resolve(replace(self.query, po_reference="PO1"), invoice_date="2026-07-31", state=state)
        self.assertEqual(used.selected.available_milli, 250)
        self.assertEqual(state.usages[0].quantity_milli, 750)

    def test_multi_po_explicit_portions_and_services(self):
        other = dict(self.orders[0], id="PO2", items=[dict(item=20, uom="mes", material="SERVICE", description="Rental", unit_price=200)])
        service = dict(self.receipts[0], id="S1", po="PO2", po_item=20, type="SES", reference="ACCEPTANCE1")
        catalog = POCatalog(orders=self.orders + [other], receipts=self.receipts + [service])
        queries = [replace(self.query, po_reference="PO1"),
                   replace(self.query, line_id="L2", uom="mes", po_reference="PO2", po_item=20)]
        results = catalog.resolve_lines(queries, invoice_date="2026-07-31")
        self.assertEqual([r.selected.order.po for r in results], ["PO1", "PO2"])
        self.assertEqual(results[1].selected.receipts[0].kind, "SES")
        self.orders[0]["items"][0]["unit_price"] = 999
        self.assertEqual(self.resolve(po_reference="PO1").selected.unit_price_cents, 100)

    def test_existing_reference_outside_scope_cannot_be_recovered_as_other_po(self):
        for changes in (dict(company="1910"), dict(vendor="OTHER"), dict(currency="USD"),
                        dict(currency="USD", created_on="2030-01-01")):
            catalog = POCatalog(orders=[*self.orders, dict(self.orders[0], id="FOREIGN", **changes)],
                                receipts=self.receipts)
            result = catalog.resolve(replace(self.query, po_reference="FOREIGN", material="M1"),
                                     invoice_date="2026-07-31")
            self.assertEqual((result.status, result.selected, result.candidates), ("CONFLICT", None, ()))
            self.assertIn("PO_REFERENCE_SCOPE_OR_DATE_CONFLICT", result.diagnostics)

    def test_future_reference_is_not_found_without_recovery_at_later_receipt_cutoff(self):
        catalog = POCatalog(orders=[*self.orders, dict(self.orders[0], id="FUTURE", created_on="2026-08-01")],
                            receipts=self.receipts)
        result = catalog.resolve(replace(self.query, po_reference="FUTURE", material="M1"),
                                 invoice_date="2026-07-31", receipt_as_of="2026-08-31")
        self.assertEqual((result.status, result.selected, result.candidates), ("NOT_FOUND", None, ()))
        self.assertEqual(result.diagnostics, ("PO_REFERENCE_AFTER_INVOICE",))
        self.assertFalse(result.reference_recovered)
        self.assertIn("PO_AFTER_INVOICE", next(d.reasons for d in result.discarded if d.order.po == "FUTURE"))

    def test_rejected_candidates_retain_specific_structural_and_concept_reasons(self):
        catalog = POCatalog(orders=[*self.orders, dict(self.orders[0], id="OTHER", currency="USD")],
                            receipts=self.receipts)
        result = catalog.resolve(replace(self.query, description="not the observed concept"),
                                 invoice_date="2026-07-31")
        self.assertTrue(all("CONCEPT_MISMATCH" in d.reasons for d in result.discarded))
        self.assertIn("CURRENCY_MISMATCH", next(d.reasons for d in result.discarded if d.order.po == "OTHER"))


if __name__ == "__main__":
    unittest.main()
