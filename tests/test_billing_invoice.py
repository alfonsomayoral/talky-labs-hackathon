from datetime import date
import unittest
from kalmora.billing import to_row, InvoiceLine
from kalmora.ledger import Ledger
from kalmora.output_validation import check_structure
from billing_support import BillingCase


class InvoiceTests(BillingCase):
    def test_number_due_dir3_assignments_cost_objects_and_owner_survive_export(self):
        result = self.run_item(self.cert()).results[0]
        row = to_row(result)
        self.assertEqual(check_structure({"ar_billing": [row]}), [])
        self.assertEqual((date.fromisoformat(result.invoice.due_date) - date.fromisoformat(result.invoice.date)).days, 30)
        self.assertEqual(row["invoice"]["face"], self.tables["customers"][0]["dir3"])
        self.assertEqual((row["invoice"]["number"], row["invoice"]["currency"], row["invoice"]["gross"]),
                         (result.invoice.number, "EUR", 36300))
        entry = row["journal_entry"]
        self.assertEqual(entry["lines"][0]["assignment"], row["invoice"]["number"])
        self.assertEqual(entry["lines"][0]["partner"], "C1")
        ledger = Ledger.from_entries([entry])
        with self.assertRaises(ValueError):
            ledger.add_entry(entry, **entry["provenance"])

    def test_missing_or_partial_dir3_blocks_public_spanish_invoice(self):
        for dir3 in (None, {}, {"oficina_contable": "L1"}):
            self.tables["customers"][0]["dir3"] = dir3
            self.assertEqual(len(self.run_item(self.cert()).unresolved), 1)

    def test_reverse_charge_preserves_policy_notice_with_zero_tax(self):
        self.tables["tax_codes"]["tax_codes"]["RISP"] = dict(kind="output_reverse", country="ES", rate=0)
        self.tables["sales_contracts"][0]["tax"] = "RISP"
        row = to_row(self.run_item(self.cert()).results[0])
        self.assertEqual(row["invoice"]["tax"], 0)
        self.assertIn("84.Uno.2º f", row["invoice"]["legal_notice"])
        self.assertIn(row["invoice"]["legal_notice"], row["journal_entry"]["header_text"])

    def test_invoice_lines_reject_float_and_boolean_money(self):
        for amount in (1.5, True):
            with self.assertRaises((TypeError, ValueError)):
                InvoiceLine("Invalid", amount, "70510000", wbs="P1.01")
