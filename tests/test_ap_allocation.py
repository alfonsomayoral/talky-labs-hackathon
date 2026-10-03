from dataclasses import replace
import unittest

from kalmora.ap_allocation import (
    ConsumptionState, InvoiceQuantityLine, OrderKey, OrderLine, OrderPortion,
    Receipt, ReceiptUsage, allocate_receipts,
)


class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.key = OrderKey("1100", "V1", "EUR", "PO1", 10)
        self.orders = [OrderLine(self.key, "ud")]
        self.receipts = [Receipt("R1", self.key, 1001, "ud", "2026-07-01"),
                         Receipt("R2", self.key, 999, "ud", "2026-07-02")]

    def line(self, qty, **kwargs):
        return InvoiceQuantityLine("L1", qty, "ud", (OrderPortion(self.key, qty),), **kwargs)

    def run_allocation(self, lines, **kwargs):
        params = dict(company="1100", vendor="V1", currency="EUR", invoice_id="I1",
                      lines=lines, orders=self.orders, receipts=self.receipts)
        params.update(kwargs)
        return allocate_receipts(**params)

    def test_partial_receipts_and_conservation_across_invoices(self):
        first = self.run_allocation([self.line(1500)])
        self.assertEqual(first.status, "ALLOCATED")
        self.assertEqual([a.quantity_milli for a in first.allocations], [1001, 499])
        self.assertEqual(sum(u.quantity_milli for u in first.state.usages), 1500)
        second = self.run_allocation([self.line(500)], state=first.state, invoice_id="I2")
        self.assertEqual([a.quantity_milli for a in second.allocations], [500])
        self.assertEqual(sum(u.quantity_milli for u in second.state.usages), 2000)
        exhausted = self.run_allocation([self.line(1)], state=second.state, invoice_id="I3")
        self.assertEqual(exhausted.diagnostics[0].available_milli, 0)
        self.assertIs(exhausted.state, second.state)
        replay = self.run_allocation([self.line(1)], state=first.state)
        self.assertEqual(replay.diagnostics[0].code, "ALREADY_ALLOCATED")

    def test_atomic_failure_and_shared_supply_within_invoice(self):
        lines = [self.line(1500), replace(self.line(501), line_id="L2")]
        result = self.run_allocation(lines)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.allocations, ())
        self.assertEqual(result.state, ConsumptionState())
        self.assertEqual(result.diagnostics[0].available_milli, 500)
        success = self.run_allocation([self.line(1500), replace(self.line(500), line_id="L2")])
        self.assertEqual(sum(a.quantity_milli for a in success.allocations), 2000)

    def test_multiple_orders_service_and_explicit_receipt(self):
        key2 = replace(self.key, po="PO2", item=20)
        orders = self.orders + [OrderLine(key2, "ud")]
        receipts = self.receipts + [Receipt("S1", key2, 1000, "ud", "2026-07-03", "SES")]
        line = InvoiceQuantityLine("L1", 1500, "ud", (
            OrderPortion(self.key, 500, ("R2",)), OrderPortion(key2, 1000, ("S1",))))
        result = self.run_allocation([line], orders=orders, receipts=receipts)
        self.assertEqual([(a.receipt_id, a.quantity_milli) for a in result.allocations],
                         [("R2", 500), ("S1", 1000)])

    def test_missing_ambiguous_erroneous_and_units(self):
        cases = [
            (replace(self.line(1), portions=()), "MISSING_REFERENCE"),
            (self.line(1, references_resolved=False), "AMBIGUOUS_REFERENCE"),
            (replace(self.line(1), portions=(OrderPortion(replace(self.key, po="absent"), 1),)), "UNKNOWN_PO_POSITION"),
            (replace(self.line(1), portions=(OrderPortion(self.key, 1, ("absent",)),)), "UNKNOWN_RECEIPT_REFERENCE"),
            (replace(self.line(1), uom="mes"), "UNIT_MISMATCH"),
            (replace(self.line(1), quantity_milli=2), "PORTION_QUANTITY_MISMATCH"),
        ]
        for line, code in cases:
            with self.subTest(code=code):
                result = self.run_allocation([line])
                self.assertEqual(result.diagnostics[0].code, code)
                self.assertEqual(result.state, ConsumptionState())

    def test_scope_isolation_and_stable_order(self):
        baseline = self.run_allocation([self.line(1500)])
        reverse = self.run_allocation([self.line(1500)], receipts=reversed(self.receipts))
        self.assertEqual(baseline, reverse)
        for field, value in (("company", "2100"), ("vendor", "V2"), ("currency", "USD")):
            foreign = replace(self.key, **{field: value})
            result = self.run_allocation([replace(self.line(1), portions=(OrderPortion(foreign, 1),))])
            self.assertEqual(result.diagnostics[0].code, "SCOPE_MISMATCH")
        foreign = replace(self.key, company="2100")
        result = self.run_allocation([self.line(2000)],
            orders=self.orders + [OrderLine(foreign, "ud")],
            receipts=self.receipts + [Receipt("R1", foreign, 9000, "ud", "2026-07-01")])
        self.assertEqual(sum(u.quantity_milli for u in result.state.usages), 2000)

    def test_invalid_catalog_and_state_cannot_reset_consumption(self):
        for qty in (True, 1.0, "1", -1, 0):
            with self.subTest(qty=qty), self.assertRaises((TypeError, ValueError)):
                self.run_allocation([replace(self.line(1), quantity_milli=qty)])
        for usages in ((ReceiptUsage(self.key, "R1", 1002),),
                       (ReceiptUsage(self.key, "missing", 1),),
                       (ReceiptUsage(self.key, "R1", 1), ReceiptUsage(self.key, "R1", 1))):
            with self.assertRaises(ValueError):
                self.run_allocation([self.line(1)], state=ConsumptionState(usages))
        with self.assertRaises(ValueError):
            self.run_allocation([self.line(1)], receipts=self.receipts + self.receipts[:1])


if __name__ == "__main__":
    unittest.main()
