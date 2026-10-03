"""Receipt certainty, not an arbitrary historical allocation."""
from dataclasses import replace
import unittest

from kalmora.ap_allocation import (
    InvoiceQuantityLine, OrderKey, OrderLine, OrderPortion, Receipt, allocate_receipts,
)
from kalmora.ap_history import HistoricalDemand, HistoricalReceipt, quantity_interval, reconcile_receipt_history
from kalmora.facts import Evidence, Fact
from kalmora.money import line_amount


class HistoricalReceiptIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.order = OrderKey("1100", "SUP-NEW", "EUR", "PO-NEW", 10)
        self.complete = Fact(True, Evidence("erp/ap_invoices.jsonl", "complete_snapshot"))

    def receipt(self, identifier, quantity, price=1000, day="2026-09-01"):
        r = Receipt(identifier, self.order, quantity, "ud", day)
        return HistoricalReceipt(r, line_amount(quantity, price), price,
                                 (Evidence("erp/goods_receipts.jsonl", f"id={identifier}"),))

    def demand(self, amount, processed_on=None):
        clock = (Fact(processed_on, Evidence("erp/processing_log.jsonl", "observed_processed_on"))
                 if processed_on is not None else None)
        return HistoricalDemand(self.order, amount,
                                (Evidence("erp/journal_entries.jsonl", "historical_ap.gr_ir"),), clock)

    def snapshot(self, receipts, demands):
        return reconcile_receipt_history(tuple(receipts), tuple(demands), inventory_complete=self.complete)

    def test_full_consumption_and_empty_inventory_are_proven_without_a_clock(self):
        receipts = [self.receipt("R1", 1000), self.receipt("R2", 1000)]
        consumed = self.snapshot(receipts, [self.demand(2000)])
        self.assertEqual([c.status for c in consumed.certainties], ["CONSUMED", "CONSUMED"])
        self.assertEqual([u.quantity_milli for u in consumed.consumption.usages], [1000, 1000])
        available = self.snapshot(receipts, [])
        self.assertEqual([c.status for c in available.certainties], ["AVAILABLE", "AVAILABLE"])
        self.assertEqual(available.consumption.usages, ())

    def test_monetary_zero_balance_does_not_prove_exact_consumption(self):
        snapshot = self.snapshot([self.receipt("R1", 1000, price=10)], [self.demand(10)])
        c, = snapshot.certainties
        self.assertEqual((c.status, c.consumed_milli), ("UNKNOWN", None))
        self.assertEqual((c.minimum_consumed_milli, c.maximum_consumed_milli), (950, 1000))
        self.assertEqual(snapshot.consumption.usages, ())
        self.assertEqual(snapshot.known_receipt_ids(self.order), ())

    def test_unique_partial_history_seeds_real_allocator_without_overconsuming(self):
        receipt = self.receipt("R-OTHER", 2000)
        snapshot = self.snapshot([receipt], [self.demand(1000)])
        c, = snapshot.certainties
        self.assertEqual((c.status, c.consumed_milli, c.known_available_milli), ("PARTIAL", 1000, 1000))
        result = allocate_receipts(
            company="1100", vendor="SUP-NEW", currency="EUR", invoice_id="OTHER-73",
            lines=[InvoiceQuantityLine("L-NEW", 1000, "ud", (
                OrderPortion(self.order, 1000, snapshot.known_receipt_ids(self.order)),))],
            orders=[OrderLine(self.order, "ud")], receipts=[receipt.receipt], state=snapshot.consumption,
        )
        self.assertEqual((result.status, result.state.usages[0].quantity_milli), ("ALLOCATED", 2000))
        self.assertEqual(snapshot.consumption.usages[0].quantity_milli, 1000)

    def test_partial_total_does_not_choose_one_of_two_historical_receipts(self):
        snapshot = self.snapshot([self.receipt("R1", 1000), self.receipt("R2", 1000)], [self.demand(1000)])
        self.assertEqual([c.status for c in snapshot.certainties], ["UNKNOWN", "UNKNOWN"])
        self.assertEqual(snapshot.consumption.usages, ())

    def test_grounded_processing_clock_can_prove_later_receipt_unused(self):
        receipts = [self.receipt("R-OLD", 1000), self.receipt("R-NEW", 1000, day="2026-09-20")]
        snapshot = self.snapshot(receipts, [self.demand(1000, "2026-09-10")])
        certainty = {c.receipt.receipt_id: c for c in snapshot.certainties}
        self.assertEqual(certainty["R-OLD"].status, "CONSUMED")
        self.assertEqual(certainty["R-NEW"].status, "AVAILABLE")
        without_clock = self.snapshot(receipts, [self.demand(1000)])
        self.assertTrue(all(c.status == "UNKNOWN" for c in without_clock.certainties))

    def test_each_historical_prefix_must_be_causally_possible(self):
        receipts = [self.receipt("R-OLD", 1000, day="2026-09-05"),
                    self.receipt("R-NEW", 1000, day="2026-09-20")]
        snapshot = self.snapshot(receipts, [self.demand(1000, "2026-09-01"),
                                            self.demand(1000, "2026-09-30")])
        self.assertTrue(all(c.status == "UNKNOWN" for c in snapshot.certainties))
        self.assertTrue(all("HISTORY_TEMPORAL_EVIDENCE_INSUFFICIENT" in c.diagnostics for c in snapshot.certainties))
        self.assertEqual(snapshot.consumption.usages, ())

    def test_bad_valuation_reversal_or_units_preserve_unknown(self):
        receipt = self.receipt("R1", 2000)
        for observations, demands in (
            ([replace(receipt, amount_doc=2001)], [self.demand(1000)]),
            ([receipt], [self.demand(-1000)]),
            ([receipt, replace(self.receipt("R2", 1000), receipt=Receipt("R2", self.order, 1000, "hours", "2026-09-01"))], [self.demand(1000)]),
        ):
            with self.subTest(observations=observations, demands=demands):
                snapshot = self.snapshot(observations, demands)
                self.assertTrue(all(c.status == "UNKNOWN" for c in snapshot.certainties))
                self.assertEqual(snapshot.consumption.usages, ())

    def test_complete_inventory_and_processing_dates_require_proof(self):
        receipts = (self.receipt("R1", 1000),)
        for assertion in (None, False, Fact(False, self.complete.evidence)):
            with self.assertRaises(ValueError):
                reconcile_receipt_history(receipts, (), inventory_complete=assertion)
        with self.assertRaises(ValueError):
            self.snapshot(receipts, [self.demand(1000, "2026-9-10")])

    def test_fractional_price_bounds_use_exact_rational_arithmetic(self):
        self.assertEqual(quantity_interval(1, "0.01"), (50000, 149999))
        self.assertEqual(quantity_interval(0, "0.01"), (0, 49999))
        with self.assertRaises(ValueError):
            quantity_interval(1, 2000)  # Integer milli steps cannot yield one cent.


if __name__ == "__main__":
    unittest.main()
