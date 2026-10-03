"""Task-order numbering and invoice/receivable identity remain coherent."""
from dataclasses import replace

from kalmora.billing import build_ar_billing, to_row
from kalmora.billing.numbering import allocate_invoice_numbers
from billing_support import BillingCase


class BillingNumberingTests(BillingCase):
    def setUp(self):
        super().setUp()
        contract = self.tables["sales_contracts"][0]
        self.tables["sales_contracts"].extend(dict(contract, id=f"CV{i}") for i in (2, 3, 4))
        self.tables["ar_invoices"] = [
            {"id": "CUSTOM26-00001", "company": "1100", "contract": "CV1", "date": "2026-06-30", "kind": "invoice"},
            {"id": "CUSTOM26-00003", "company": "1100", "contract": "CV2", "date": "2026-06-30", "kind": "invoice"},
        ]
        self.items = [self.item(id="B2", contract="CV2"), self.item(id="B1")]
        self.facts = {item.id: self.cert() for item in self.items}

    def bill(self, items=None, facts=None, **options):
        return build_ar_billing(self.data(), items or self.items, self.facts if facts is None else facts, **options)

    def test_gap_fill_in_task_order_preserves_invoice_journal_and_receivable_identity(self):
        data = self.data()
        preliminary = build_ar_billing(data, self.items, self.facts)
        numbers = allocate_invoice_numbers(data, self.items, preliminary)
        self.assertEqual(numbers, {"B2": "CUSTOM26-00002", "B1": "CUSTOM26-00004"})
        rebuilt = build_ar_billing(data, self.items, self.facts, invoice_numbers=numbers)
        self.assertEqual(rebuilt.unresolved, ())
        for before, after in zip(preliminary.results, rebuilt.results):
            row = to_row(after)
            number = numbers[after.item.id]
            self.assertEqual(after.invoice.number, number)
            self.assertEqual(after.journal_entry["reference"], number)
            receivable = next(line for line in row["journal_entry"]["lines"] if line["account"] == "43000000")
            self.assertEqual((receivable["assignment"], receivable["partner"], receivable["debit"]),
                             (number, after.item.customer, before.invoice.payable))
            self.assertEqual(after.invoice.net, before.invoice.net)
            self.assertEqual(after.invoice.date, before.invoice.date)
            self.assertEqual(after.invoice.due_date, before.invoice.due_date)

    def test_default_max_plus_one_behavior_is_unchanged(self):
        billing = self.bill()
        self.assertEqual({result.item.id: result.invoice.number for result in billing.results},
                         {"B2": "CUSTOM26-00005", "B1": "CUSTOM26-00004"})

    def test_preliminary_result_order_does_not_change_task_allocation(self):
        data = self.data()
        preliminary = build_ar_billing(data, self.items, self.facts)
        reordered = replace(preliminary, results=tuple(reversed(preliminary.results)))
        self.assertEqual(allocate_invoice_numbers(data, self.items, preliminary),
                         allocate_invoice_numbers(data, self.items, reordered))
        reversed_tasks = allocate_invoice_numbers(data, list(reversed(self.items)), preliminary)
        self.assertEqual(reversed_tasks, {"B1": "CUSTOM26-00002", "B2": "CUSTOM26-00004"})

    def test_pending_and_unresolved_items_do_not_consume_numbers(self):
        items = [self.item(id="PENDING", contract="CV3"), self.item(id="UNKNOWN", contract="CV4"), *self.items]
        facts = {"PENDING": self.cert(approved=False), **self.facts}
        data = self.data()
        preliminary = build_ar_billing(data, items, facts)
        numbers = allocate_invoice_numbers(data, items, preliminary)
        self.assertEqual(numbers, {"B2": "CUSTOM26-00002", "B1": "CUSTOM26-00004"})
        self.assertEqual(len(preliminary.pending_wip), 1)
        self.assertEqual([unresolved.item.id for unresolved in preliminary.unresolved], ["UNKNOWN"])

    def test_collision_alias_wrong_series_and_duplicate_overrides_fail_closed(self):
        for numbers in ({"B1": "CUSTOM26-00001"}, {"B1": "CUSTOM26-1"},
                        {"B1": "OTHER26-00002"}, {"B1": "CUSTOM26-00000"}):
            with self.subTest(numbers=numbers):
                run = self.bill(invoice_numbers=numbers)
                self.assertIn("B1", {unresolved.item.id for unresolved in run.unresolved})
        duplicate = self.bill(invoice_numbers={"B1": "CUSTOM26-00002", "B2": "CUSTOM26-2"})
        self.assertEqual(len(duplicate.unresolved), 1)
        self.assertIn("collides", duplicate.unresolved[0].reasons[0])

    def test_unknown_items_and_invalid_override_types_are_rejected(self):
        for numbers in ({"NO-TASK": "CUSTOM26-00002"}, {"B1": ""}, {"B1": 2}):
            with self.subTest(numbers=numbers), self.assertRaises(ValueError):
                self.bill(invoice_numbers=numbers)

    def test_new_year_and_other_series_are_derived_from_built_invoices(self):
        new_year = [replace(item, month="2027-01") for item in self.items]
        facts = {item.id: self.cert(month="2027-01") for item in new_year}
        data = self.data()
        preliminary = build_ar_billing(data, new_year, facts)
        self.assertEqual(allocate_invoice_numbers(data, new_year, preliminary),
                         {"B2": "CUSTOM27-00001", "B1": "CUSTOM27-00002"})
        self.tables["ar_invoices"][1]["id"] = "ALTERNATE26-00007"
        data = self.data()
        preliminary = build_ar_billing(data, self.items, self.facts)
        self.assertEqual(allocate_invoice_numbers(data, self.items, preliminary),
                         {"B2": "ALTERNATE26-00001", "B1": "CUSTOM26-00002"})

    def test_partial_override_avoids_collision_with_following_default_number(self):
        billing = self.bill(invoice_numbers={"B1": "CUSTOM26-00004"})
        self.assertEqual(billing.unresolved, ())
        self.assertEqual({result.item.id: result.invoice.number for result in billing.results},
                         {"B2": "CUSTOM26-00005", "B1": "CUSTOM26-00004"})

    def test_inventory_mismatch_is_rejected_without_mutating_preliminary_run(self):
        data = self.data()
        preliminary = build_ar_billing(data, self.items, self.facts)
        original = tuple(result.invoice.number for result in preliminary.results)
        for inventory in (self.items * 2, self.items[:1], [replace(self.items[0], month="2026-08"), self.items[1]]):
            with self.assertRaises(ValueError):
                allocate_invoice_numbers(data, inventory, preliminary)
        self.assertEqual(tuple(result.invoice.number for result in preliminary.results), original)
