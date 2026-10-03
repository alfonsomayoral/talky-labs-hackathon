"""Phase source join exercised with the real certainty and quantity engines."""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalmora.ap_allocation import InvoiceQuantityLine, OrderPortion, allocate_receipts
from kalmora.ap_erp import load_ap_erp_baseline
from kalmora.data import PhaseData


class APERPIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.phase = Path(self.tmp.name) / "phase"
        (self.phase / "erp").mkdir(parents=True)
        (self.phase / "tasks").mkdir()
        self.close("2031-11")
        self.order = dict(id="PO-NEW", company="1100", vendor="V-NEW", currency="EUR",
            created_on="2031-10-01", items=[dict(item=10, uom="hours", unit_price=1000)])
        self.receipt = dict(id="R-NEW", company="1100", vendor="V-NEW", po="PO-NEW", po_item=10,
            type="SES", quantity_milli=2000, amount=2000, posting_date="2031-10-20")
        self.invoice = dict(doc_id="DOC-NEW", company="1100", vendor="V-NEW", currency="EUR",
            kind="invoice", number="F-72", received_on="2031-10-21", posted_on="2031-10-22",
            gross=1000, decision="HOLD", journal_entry="JE-NEW")
        self.log = dict(self.invoice, resolved_on="2031-10-22", reasons=["QTY_NOT_RECEIVED"])
        self.entry = dict(id="JE-NEW", company="1100", currency="EUR", source="AP",
            reference="F-72", posting_date="2031-10-22", document_date="2031-10-01", lines=[
                dict(account="40090000", debit=1000, credit=0, currency="EUR", amount_doc=1000,
                     partner="V-NEW", assignment="PO-NEW/10"),
                dict(account="41000000", debit=0, credit=1000, currency="EUR", amount_doc=1000,
                     partner="V-NEW", assignment="F-72")])
        self.write("purchase_orders", [self.order])
        self.write("goods_receipts", [self.receipt])
        self.write("vendors", [dict(id="V-NEW")])
        self.history([self.invoice], [self.log], [self.entry])

    def close(self, month):
        (self.phase / "tasks" / "close.json").write_text(json.dumps(dict(month=month)))

    def write(self, table, rows):
        (self.phase / "erp" / (table + ".jsonl")).write_text(
            "".join(json.dumps(row) + "\n" for row in rows))

    def history(self, invoices, logs, entries):
        self.write("ap_invoices", invoices)
        self.write("ap_document_log", logs)
        self.write("journal_entries", entries)

    def load(self):
        return load_ap_erp_baseline(self.phase, grir_account="40090000")

    def test_resolved_hold_seeds_partial_consumption_and_protects_the_recorded_id(self):
        baseline = self.load()
        self.assertEqual(baseline.month, "2031-11")
        self.assertEqual(baseline.history.certainties[0].status, "PARTIAL")
        self.assertEqual(baseline.history.consumption.usages[0].quantity_milli, 1000)
        self.assertEqual(baseline.history.consumption.invoices, (("1100", "V-NEW", "EUR", "DOC-NEW"),))
        guard = baseline.posting_guard(company="1100", vendor="V-NEW", currency="EUR",
                                       doc_id="DOC-NEW", number="F-72")
        self.assertEqual(guard.status, "ALREADY_POSTED")
        allocation = allocate_receipts(company="1100", vendor="V-NEW", currency="EUR", invoice_id="LATER",
            lines=(InvoiceQuantityLine("L1", 1000, "hours", (OrderPortion(
                baseline.orders[0].key, 1000, baseline.history.known_receipt_ids(baseline.orders[0].key)),)),),
            orders=baseline.orders, receipts=baseline.receipts, state=baseline.history.consumption)
        self.assertEqual(allocation.status, "ALLOCATED")
        self.assertEqual(allocation.state.usages[0].quantity_milli, 2000)
        self.assertEqual(baseline.history.consumption.usages[0].quantity_milli, 1000)
        self.assertEqual(baseline.duplicate_records[0].status, "HOLD")
        self.assertEqual(baseline.duplicate_records[0].evidence[0].document, "erp/ap_invoices.jsonl")

    def test_all_ap_grir_journals_count_even_without_an_invoice_link(self):
        self.history([], [], [self.entry])
        baseline = self.load()
        self.assertEqual(baseline.history.certainties[0].consumed_milli, 1000)
        self.assertEqual(baseline.history.consumption.invoices, ())
        self.assertEqual(baseline.recorded_postings[0].document_ids, ())
        guard = baseline.posting_guard(company="1100", vendor="V-NEW", currency="EUR",
                                       doc_id="OTHER-ID", number="F/72")
        self.assertEqual((guard.status, guard.diagnostics), ("UNKNOWN", ("UNLINKED_AP_JOURNAL_IDENTITY",)))

    def test_direct_unlinked_posting_does_not_invent_a_document_or_consume_receipts(self):
        entry = dict(self.entry, reference="IC-31-82", lines=[dict(
            self.entry["lines"][0], account="62940000", assignment="IC-31-82"), self.entry["lines"][1]])
        self.history([], [], [entry])
        baseline = self.load()
        self.assertEqual(baseline.history.certainties[0].status, "AVAILABLE")
        self.assertEqual(baseline.history.consumption.invoices, ())
        for vendor, currency, number, expected in (
            ("V-NEW", "EUR", "IC3182", "UNKNOWN"), ("V-OTHER", "EUR", "IC3182", "CLEAR"),
            ("V-NEW", "USD", "IC3182", "CLEAR"), ("V-NEW", "EUR", "OTHER", "CLEAR")):
            guard = baseline.posting_guard(company="1100", vendor=vendor, currency=currency,
                                           doc_id="NEW", number=number)
            self.assertEqual(guard.status, expected)

    def test_accrual_reversal_is_not_ap_receipt_consumption(self):
        self.history([], [], [dict(self.entry, source="CLOSE", lines=[dict(
            self.entry["lines"][0], debit=0, credit=1000)])])
        baseline = self.load()
        self.assertEqual(baseline.history.certainties[0].status, "AVAILABLE")
        self.assertEqual(baseline.recorded_postings, ())

    def test_journal_date_does_not_supply_a_processing_clock_or_choose_fifo(self):
        second = dict(self.receipt, id="R-LATER", posting_date="2031-11-02")
        self.write("goods_receipts", [dict(self.receipt, quantity_milli=1000, amount=1000),
                                     dict(second, quantity_milli=1000, amount=1000)])
        baseline = self.load()
        self.assertEqual([c.status for c in baseline.history.certainties], ["UNKNOWN", "UNKNOWN"])
        self.assertEqual(baseline.history.consumption.usages, ())

    def test_credit_without_explicit_restoration_preserves_unknown_quantity(self):
        entry = dict(self.entry, lines=[dict(self.entry["lines"][0], debit=0, credit=1000),
                                       dict(self.entry["lines"][1], debit=1000, credit=0)])
        self.history([self.invoice], [self.log], [entry])
        baseline = self.load()
        self.assertEqual(baseline.history.certainties[0].status, "UNKNOWN")
        self.assertEqual(baseline.history.consumption.usages, ())

    def test_missing_or_conflicting_links_and_scope_fail_before_posting(self):
        for entries in ([], [dict(self.entry, source="CLOSE")],
                        [dict(self.entry, lines=[dict(line, currency="USD") for line in self.entry["lines"]])],
                        [dict(self.entry, lines=[dict(self.entry["lines"][0], partner="V-OTHER")])],
                        [dict(self.entry, lines=[dict(self.entry["lines"][0], assignment="GUESSED")])],
                        [self.entry, self.entry]):
            with self.subTest(entries=entries):
                self.history([self.invoice], [self.log], entries)
                with self.assertRaises(ValueError):
                    self.load()
        self.history([self.invoice], [dict(self.log, journal_entry="OTHER")], [self.entry])
        with self.assertRaisesRegex(ValueError, "contradictory posted identity"):
            self.load()

    def test_new_phase_load_never_reuses_previous_snapshot_or_inputs(self):
        old = self.load()
        self.close("2032-02")
        self.history([], [], [])
        new = self.load()
        self.assertEqual((old.month, new.month), ("2031-11", "2032-02"))
        self.assertEqual((old.history.certainties[0].consumed_milli, new.history.certainties[0].consumed_milli),
                         (1000, 0))
        self.assertNotEqual(old.sources, new.sources)
        self.assertEqual(self.load(), new)

    def test_document_currency_survives_local_journal_header_and_historical_407_currency(self):
        order = dict(self.order, currency="USD")
        self.write("purchase_orders", [order])
        invoice, log = dict(self.invoice, currency="USD"), dict(self.log, currency="USD")
        # Debit/credit are local cents; amount_doc remains explicit USD cents.
        lines = [dict(line, currency="USD", debit=line["debit"] * 9 // 10,
                      credit=line["credit"] * 9 // 10) for line in self.entry["lines"]]
        lines[1] = dict(lines[1], credit=800, amount_doc=889)
        lines.append(dict(account="40700000", debit=0, credit=100, currency="EUR",
                          amount_doc=100, partner="V-NEW", assignment="OLD-ADVANCE"))
        self.history([invoice], [log], [dict(self.entry, currency="EUR", lines=lines)])
        baseline = self.load()
        posting, = baseline.recorded_postings
        self.assertEqual((posting.currency, posting.journal_currency), ("USD", "EUR"))
        self.assertEqual(baseline.history.certainties[0].consumed_milli, 1000)
        self.assertEqual(baseline.history.consumption.invoices[0][2], "USD")

    def test_concurrent_source_change_and_source_symlink_escape_are_rejected(self):
        original = PhaseData.iter_journal
        def changed(data):
            yield from original(data)
            self.write("purchase_orders", [dict(self.order, project="NEW")])
        with patch.object(PhaseData, "iter_journal", changed):
            with self.assertRaisesRegex(ValueError, "source changed"):
                self.load()
        target = self.phase / "erp" / "goods_receipts.jsonl"
        target.unlink()
        external = Path(self.tmp.name) / "external.jsonl"
        external.write_text(json.dumps(self.receipt) + "\n")
        target.symlink_to(external)
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.load()

    def test_golden_is_not_an_available_phase(self):
        golden = self.phase / "golden"
        golden.mkdir()
        with self.assertRaisesRegex(ValueError, "Golden"):
            load_ap_erp_baseline(golden, grir_account="40090000")


if __name__ == "__main__":
    unittest.main()
