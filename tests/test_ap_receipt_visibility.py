"""Separate arrival-time receipt availability from invoice-date valuation."""
from dataclasses import replace
import unittest

from kalmora.ap_allocation import (
    InvoiceQuantityLine, OrderLine, OrderPortion, allocate_receipts,
)
from kalmora.ap_orders import POCatalog, POQuery
from kalmora.ap_valuation import CostAssignment, OrderPrice, ValuationLine, value_ap_lines
from kalmora.facts import Evidence
from kalmora.money import RateTable


class ReceiptVisibilityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.invoice_date = "2026-09-01"
        self.received_on = "2026-09-11"
        self.orders = [dict(id="PO-OTHER", company="1100", vendor="SUP-OTHER",
                            currency="USD", created_on="2026-08-01", items=[
                                dict(item=10, uom="ud", unit_price=10000)])]
        self.receipts = [dict(id=identifier, company="1100", vendor="SUP-OTHER",
                             po="PO-OTHER", po_item=10, quantity_milli=1000,
                             posting_date=day, type="GR", reference=reference)
                         for identifier, day, reference in (
                             ("R-AVAILABLE", "2026-09-03", "DELIVERY-AVAILABLE"),
                             ("R-FUTURE", "2026-09-12", "DELIVERY-FUTURE"))]
        self.catalog = POCatalog(orders=self.orders, receipts=self.receipts)
        self.query = POQuery("LINE-OTHER", "1100", "SUP-OTHER", "USD", 1000, "ud",
                             (Evidence("inbox/ap/OTHER-73/invoice.pdf", "line.1.po"),),
                             po_reference="PO-OTHER", po_item=10)

    def test_arrival_cutoff_makes_intervening_receipt_available_without_future_supply(self):
        legacy = self.catalog.resolve(self.query, invoice_date=self.invoice_date)
        self.assertEqual(legacy.selected.available_milli, 0)
        result = self.catalog.resolve(self.query, invoice_date=self.invoice_date,
                                      receipt_as_of=self.received_on)
        self.assertEqual(result.selected.available_milli, 1000)
        self.assertEqual([r.receipt_id for r in result.selected.receipts], ["R-AVAILABLE"])

    def test_referenced_receipt_uses_same_cutoff_and_future_reference_remains_unknown(self):
        available = replace(self.query, receipt_references=("DELIVERY-AVAILABLE",))
        self.assertEqual(self.catalog.resolve(available, invoice_date=self.invoice_date).status, "UNKNOWN")
        self.assertEqual(self.catalog.resolve(available, invoice_date=self.invoice_date,
                                             receipt_as_of=self.received_on).status, "RESOLVED")
        future = replace(self.query, receipt_references=("DELIVERY-FUTURE",))
        result = self.catalog.resolve(future, invoice_date=self.invoice_date,
                                      receipt_as_of=self.received_on)
        self.assertEqual((result.status, result.selected), ("UNKNOWN", None))
        self.assertEqual(result.candidates[0].receipts, ())

    def test_processing_cutoff_cannot_enable_order_created_after_invoice(self):
        catalog = POCatalog(orders=[{**self.orders[0], "created_on": "2026-09-02"}],
                            receipts=self.receipts)
        result = catalog.resolve(self.query, invoice_date=self.invoice_date,
                                  receipt_as_of=self.received_on)
        self.assertEqual((result.status, result.selected), ("NOT_FOUND", None))

    def test_batch_forwards_cutoff_and_rejects_noncanonical_dates(self):
        result, = self.catalog.resolve_lines([self.query], invoice_date=self.invoice_date,
                                             receipt_as_of=self.received_on)
        self.assertEqual(result.selected.available_milli, 1000)
        for cutoff in ("2026-9-11", "2026-09-31", "2026-09-11T08:00:00", ""):
            with self.assertRaises(ValueError):
                self.catalog.resolve(self.query, invoice_date=self.invoice_date,
                                     receipt_as_of=cutoff)

    def test_allocation_and_fx_keep_invoice_date_after_receipt_selection(self):
        selected = self.catalog.resolve(self.query, invoice_date=self.invoice_date,
                                        receipt_as_of=self.received_on).selected
        eligible_ids = tuple(r.receipt_id for r in selected.receipts)
        allocation = allocate_receipts(
            company="1100", vendor="SUP-OTHER", currency="USD", invoice_id="OTHER-73",
            lines=[InvoiceQuantityLine("LINE-OTHER", 1000, "ud", (
                OrderPortion(selected.order, 1000, eligible_ids),))],
            orders=[OrderLine(selected.order, "ud")], receipts=selected.receipts,
        )
        rates = RateTable([dict(currency="USD", date=self.invoice_date, rate="2"),
                           dict(currency="USD", date=self.received_on, rate="4")])
        valuation = value_ap_lines(
            company="1100", vendor="SUP-OTHER", currency="USD", invoice_id="OTHER-73",
            invoice_date=self.invoice_date, decision="POST", gr_ir_account="40090000",
            lines=[ValuationLine("LINE-OTHER", 10000,
                                 CostAssignment("1100", "62300000", "CC-OTHER"), 1000)],
            allocation=allocation, prices=[OrderPrice(selected.order, selected.unit_price_cents)],
            rates=rates,
        )
        self.assertEqual([a.receipt_id for a in allocation.allocations], ["R-AVAILABLE"])
        self.assertEqual((valuation.net_doc, valuation.net_local), (10000, 5000))
        self.assertEqual(valuation.scope.invoice_date, self.invoice_date)
        self.assertNotEqual(valuation.net_local, rates.to_local(10000, "USD", "1100", self.received_on))


if __name__ == "__main__":
    unittest.main()
