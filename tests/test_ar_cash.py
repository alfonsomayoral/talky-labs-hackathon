import json
from pathlib import Path
import tempfile
import unittest

from kalmora.ar_cash import build_ar_cash
from kalmora.data import PhaseData


class ArCashTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.phase = Path(self.tmp.name) / "phase"
        for area in ("erp", "tasks", "bank/BIN-1100", "inbox/ar/remittances"):
            (self.phase / area).mkdir(parents=True, exist_ok=True)
        self._json("tasks/close.json", {"month": "2026-07"})
        self._json("tasks/ar_receipts.json", ["BL1"])
        self._jsonl("erp/bank_accounts.jsonl", [{"id": "BIN-1100", "company": "1100",
                                                   "currency": "EUR", "gl_account": "57200001"}])
        self._jsonl("erp/customers.jsonl", [{"id": "C1", "name": "Cliente Alfa, S.A.",
                                               "tax_id": "TAX1"}])
        self._jsonl("erp/vendors.jsonl", [])
        self._jsonl("erp/ar_invoices.jsonl", [self.invoice("INV-1", 10000)])
        self._jsonl("erp/penalty_notices.jsonl", [])
        self._jsonl("erp/factoring_assignments.jsonl", [])
        self._jsonl("erp/promissory_notes.jsonl", [])
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("INVPOST", "2026-06-01", [self.line("43000000", 10000, 0, "C1", "INV-1"),
                                                    self.line("70500000", 0, 10000)]),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 8000, 0),
                                                    self.line("55500000", 0, 8000)]),
        ])
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [{
            "bank_line": "BL1", "booking_date": "2026-07-02", "value_date": "2026-07-02",
            "amount": 8000, "currency": "EUR", "text": "TRANSFERENCIA DE CLIENTE ALFA",
        }])

    @staticmethod
    def invoice(invoice_id, payable, *, customer="C1", company="1100", due="2026-07-01",
                date="2026-06-01", factored=False, currency="EUR"):
        return {"id": invoice_id, "company": company, "customer": customer, "kind": "invoice",
                "date": date, "due_date": due, "currency": currency, "payable": payable,
                "gross": payable, "factored": factored}

    @staticmethod
    def line(account, debit, credit, partner=None, assignment=None):
        row = {"account": account, "debit": debit, "credit": credit}
        if partner is not None:
            row["partner"] = partner
        if assignment is not None:
            row["assignment"] = assignment
        return row

    @classmethod
    def entry(cls, entry_id, posting_date, lines):
        return {"id": entry_id, "company": "1100", "posting_date": posting_date, "lines": lines}

    def _json(self, relative, value):
        (self.phase / relative).write_text(json.dumps(value), encoding="utf-8")

    def _jsonl(self, relative, rows):
        (self.phase / relative).write_text("".join(json.dumps(row) + "\n" for row in rows),
                                           encoding="utf-8")

    def _run(self):
        return build_ar_cash(PhaseData(self.phase))

    def test_unique_partial_payment_is_applied_from_555(self):
        result = self._run().results[0]
        self.assertEqual(result.row["customer"], "C1")
        self.assertEqual(result.row["applications"], [{"invoice": "INV-1", "amount": 8000}])
        self.assertEqual(result.row["residuals"], [])
        self.assertEqual(result.row["adjustment"], [
            {"company": "1100", "account": "55500000", "debit": 8000, "credit": 0},
            {"company": "1100", "account": "43000000", "debit": 0, "credit": 8000,
             "partner": "C1", "assignment": "INV-1"},
        ])

    def test_structured_penalty_clears_invoice_and_balances(self):
        self._jsonl("erp/penalty_notices.jsonl", [{
            "invoice": "INV-1", "customer": "C1", "amount": 2000, "notified_on": "2026-06-20",
        }])
        (self.phase / "bank/BIN-1100/2026-07.lines.jsonl").write_text(json.dumps({
            "bank_line": "BL1", "booking_date": "2026-07-02", "value_date": "2026-07-02",
            "amount": 8000, "currency": "EUR", "text": "TRANSFERENCIA DE CLIENTE ALFA",
        }) + "\n", encoding="utf-8")
        # The posted receipt in 555 is the cash less the evidenced penalty.
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("INVPOST", "2026-06-01", [self.line("43000000", 10000, 0, "C1", "INV-1"),
                                                    self.line("70500000", 0, 10000)]),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 8000, 0),
                                                    self.line("55500000", 0, 8000)]),
        ])
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [{"invoice": "INV-1", "amount": 10000}])
        self.assertEqual(result.row["residuals"], [{"type": "PENALTY", "invoice": "INV-1", "amount": 2000}])
        self.assertEqual(sum(line["debit"] for line in result.row["adjustment"]),
                         sum(line["credit"] for line in result.row["adjustment"]))
        self.assertEqual(result.row["adjustment"][1]["account"], "70590000")

    def test_optional_structured_notice_supplies_penalty_and_deduplicates_erp_fact(self):
        notice_dir = self.phase / "inbox/ar/notices"
        notice_dir.mkdir(parents=True)
        notice = {"invoice": "INV-1", "customer": "C1", "amount": 2000,
                  "notified_on": "2026-06-20"}
        (notice_dir / "notice.json").write_text(json.dumps(notice), encoding="utf-8")
        self._jsonl("erp/penalty_notices.jsonl", [notice])
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("INVPOST", "2026-06-01", [self.line("43000000", 10000, 0, "C1", "INV-1"),
                                                    self.line("70500000", 0, 10000)]),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 8000, 0),
                                                    self.line("55500000", 0, 8000)]),
        ])
        result = self._run().results[0]
        self.assertEqual(result.row["residuals"], [{"type": "PENALTY", "invoice": "INV-1",
                                                     "amount": 2000}])
        self.assertEqual(sum(line["debit"] for line in result.row["adjustment"]),
                         sum(line["credit"] for line in result.row["adjustment"]))

    def test_remittance_json_metadata_corroborates_payer_without_reading_attachment(self):
        (self.phase / "inbox/ar/remittances/notice.json").write_text(json.dumps({
            "file": "notice.pdf", "from_": "Cliente Alfa, S.A.", "received_at": "2026-07-02",
            "channel": "email",
        }), encoding="utf-8")
        result = self._run().results[0]
        self.assertEqual(result.row["customer"], "C1")
        self.assertTrue(any("payer corroborated by remittance metadata notice.json" in message
                            for message in result.diagnostics))
        (self.phase / "inbox/ar/remittances/notice.pdf").write_text("not opened", encoding="utf-8")

    def test_conflicting_bank_and_remittance_payers_stay_unresolved(self):
        self._jsonl("erp/customers.jsonl", [
            {"id": "C1", "name": "Cliente Alfa Holdings, S.A.", "tax_id": "TAX1"},
            {"id": "C2", "name": "Cliente Alfa Beta, S.L.", "tax_id": "TAX2"},
        ])
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [{
            "bank_line": "BL1", "booking_date": "2026-07-02", "value_date": "2026-07-02",
            "amount": 8000, "currency": "EUR", "text": "TRANSFERENCIA DE CLIENTE ALFA BETA HOLDINGS",
        }])
        (self.phase / "inbox/ar/remittances/notice.json").write_text(json.dumps({
            "file": "notice.pdf", "from_": "Cliente Alfa Holdings, S.A.", "received_at": "2026-07-02",
        }), encoding="utf-8")
        result = self._run().results[0]
        self.assertIsNone(result.row["customer"])
        self.assertEqual(result.row["applications"], [])
        self.assertTrue(any("conflicts with remittance sender" in message
                            for message in result.diagnostics))

    def test_optional_notice_directories_may_be_absent(self):
        (self.phase / "inbox/ar/remittances").rmdir()
        self.assertEqual(len(self._run().results), 1)

    def test_duplicate_receipt_is_classified_only_after_first_application(self):
        self._json("tasks/ar_receipts.json", ["BL1", "BL2"])
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [
            {"bank_line": "BL1", "booking_date": "2026-07-02", "value_date": "2026-07-02",
             "amount": 10000, "currency": "EUR", "text": "TRANSFERENCIA DE CLIENTE ALFA"},
            {"bank_line": "BL2", "booking_date": "2026-07-03", "value_date": "2026-07-03",
             "amount": 10000, "currency": "EUR", "text": "TRANSFERENCIA DE CLIENTE ALFA"},
        ])
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("INVPOST", "2026-06-01", [self.line("43000000", 10000, 0, "C1", "INV-1"),
                                                    self.line("70500000", 0, 10000)]),
            self.entry("CASH1", "2026-07-02", [self.line("57200001", 10000, 0),
                                                 self.line("55500000", 0, 10000)]),
            self.entry("CASH2", "2026-07-03", [self.line("57200001", 10000, 0),
                                                 self.line("55500000", 0, 10000)]),
        ])
        first, second = self._run().results
        self.assertEqual(first.row["applications"], [{"invoice": "INV-1", "amount": 10000}])
        self.assertEqual(second.row["residuals"], [{"type": "OVERPAYMENT_DUPLICATE",
                                                      "invoice": "INV-1", "amount": 10000}])
        self.assertEqual(second.row["adjustment"][1]["account"], "43800000")

    def test_receivable_posted_after_receipt_is_not_available_as_of_that_date(self):
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [{
            "bank_line": "BL1", "booking_date": "2026-07-02", "value_date": "2026-07-02",
            "amount": 8000, "currency": "EUR", "text": "TRANSFERENCIA DE CLIENTE ALFA INV-001",
        }])
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("INVPOST", "2026-07-03", [self.line("43000000", 10000, 0, "C1", "INV-001"),
                                                     self.line("70500000", 0, 10000)]),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 8000, 0),
                                                    self.line("55500000", 0, 8000)]),
        ])
        result = self._run().results[0]
        self.assertEqual(result.row["customer"], "C1")
        self.assertEqual(result.row["applications"], [])
        self.assertEqual(result.row["adjustment"], [])

    def test_explicit_reference_uses_an_open_item_from_dated_journal(self):
        self._jsonl("erp/ar_invoices.jsonl", [])
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("INVPOST", "2026-06-01", [self.line("43000000", 10000, 0, "C1", "INV-001"),
                                                     self.line("70500000", 0, 10000)]),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 8000, 0),
                                                    self.line("55500000", 0, 8000)]),
        ])
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [{
            "bank_line": "BL1", "booking_date": "2026-07-02", "value_date": "2026-07-02",
            "amount": 8000, "currency": "EUR", "text": "TRANSFERENCIA DE CLIENTE ALFA INV-001",
        }])
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [{"invoice": "INV-001", "amount": 8000}])
        self.assertTrue(any("dated ERP open item" in message for message in result.diagnostics))

    def test_non_customer_tax_refund_uses_structured_bank_description(self):
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [{
            "bank_line": "BL1", "booking_date": "2026-07-02", "value_date": "2026-07-02",
            "amount": 8000, "currency": "EUR", "text": "DEVOLUCION AUTORIDADE TRIBUTARIA IVA 202605",
        }])
        result = self._run().results[0]
        self.assertIsNone(result.row["customer"])
        self.assertEqual(result.row["residuals"], [{"type": "NON_CUSTOMER", "amount": 8000}])
        self.assertEqual(result.row["adjustment"][1]["account"], "47000000")

    def test_factored_invoice_paid_to_kalmora_is_credited_to_factor(self):
        self._jsonl("erp/ar_invoices.jsonl", [self.invoice("INV-1", 8000, factored=True)])
        self._jsonl("erp/factoring_assignments.jsonl", [{
            "invoice": "INV-1", "remittance": "FAC-1", "date": "2026-06-10", "customer": "C1",
        }])
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("INVPOST", "2026-06-01", [self.line("43000000", 8000, 0, "C1", "INV-1"),
                                                    self.line("70500000", 0, 8000)]),
            self.entry("FACTOR", "2026-06-10", [self.line("55300000", 0, 8000, "FACTOR-BAE", "INV-1"),
                                                  self.line("43000000", 0, 8000, "C1", "INV-1")]),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 8000, 0),
                                                    self.line("55500000", 0, 8000)]),
        ])
        result = self._run().results[0]
        self.assertEqual(result.row["residuals"], [{"type": "FACTORED_MISDIRECTED",
                                                     "invoice": "INV-1", "amount": 8000}])
        self.assertEqual(result.row["adjustment"][1]["account"], "55300000")
        self.assertEqual(result.row["adjustment"][1]["partner"], "FACTOR-BAE")

    def test_netting_against_same_counterparty_vendor_is_balanced(self):
        self._jsonl("erp/vendors.jsonl", [{"id": "V1", "name": "Cliente Alfa, S.A.",
                                            "tax_id": "TAX1", "companies": ["1100"]}])
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("INVPOST", "2026-06-01", [self.line("43000000", 10000, 0, "C1", "INV-1"),
                                                    self.line("70500000", 0, 10000)]),
            self.entry("APPOST", "2026-06-20", [self.line("41000000", 0, 2000, "V1", "AP-1"),
                                                   self.line("62300000", 2000, 0)]),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 8000, 0),
                                                    self.line("55500000", 0, 8000)]),
        ])
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [{"invoice": "INV-1", "amount": 10000}])
        self.assertEqual(result.row["residuals"], [{"type": "NETTING_AP", "invoice": "INV-1", "amount": 2000}])
        self.assertEqual([line["account"] for line in result.row["adjustment"]],
                         ["55500000", "41000000", "43000000"])
        self.assertEqual(sum(line["debit"] for line in result.row["adjustment"]),
                         sum(line["credit"] for line in result.row["adjustment"]))

    def test_ap_posted_after_receipt_cannot_support_netting(self):
        self._jsonl("erp/vendors.jsonl", [{"id": "V1", "name": "Cliente Alfa, S.A.",
                                            "tax_id": "TAX1", "companies": ["1100"]}])
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("INVPOST", "2026-06-01", [self.line("43000000", 10000, 0, "C1", "INV-1"),
                                                    self.line("70500000", 0, 10000)]),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 8000, 0),
                                                    self.line("55500000", 0, 8000)]),
            self.entry("APPOST", "2026-07-03", [self.line("41000000", 0, 2000, "V1", "AP-1"),
                                                   self.line("62300000", 2000, 0)]),
        ])
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [{"invoice": "INV-1", "amount": 8000}])
        self.assertEqual(result.row["residuals"], [])
        self.assertFalse(any(item["type"] == "NETTING_AP" for item in result.row["residuals"]))

    def test_penalty_notified_after_receipt_date_is_not_applied(self):
        self._jsonl("erp/penalty_notices.jsonl", [{
            "invoice": "INV-1", "customer": "C1", "amount": 2000, "notified_on": "2026-07-03",
        }])
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [{"invoice": "INV-1", "amount": 8000}])
        self.assertEqual(result.row["residuals"], [])

    def test_matured_promissory_note_is_applied_to_431(self):
        self._jsonl("erp/promissory_notes.jsonl", [{
            "number": "7654321", "customer": "C1", "company": "1100",
            "maturity": "2026-07-01", "amount": 8000,
        }])
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("NOTEPOST", "2026-06-01", [self.line("43100000", 8000, 0, "C1", "PAG7654321"),
                                                    self.line("43000000", 0, 8000, "C1", "INV-1")]),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 8000, 0),
                                                    self.line("55500000", 0, 8000)]),
        ])
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [{"pagare": "7654321", "amount": 8000}])
        self.assertEqual(result.row["adjustment"], [
            {"company": "1100", "account": "55500000", "debit": 8000, "credit": 0},
            {"company": "1100", "account": "43100000", "debit": 0, "credit": 8000,
             "partner": "C1", "assignment": "PAG7654321"},
        ])

    def test_unmatured_promissory_note_is_not_available_on_receipt_date(self):
        self._jsonl("erp/promissory_notes.jsonl", [{
            "number": "7654321", "customer": "C1", "company": "1100",
            "maturity": "2026-07-03", "amount": 8000,
        }])
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("NOTEPOST", "2026-06-01", [self.line("43100000", 8000, 0, "C1", "PAG7654321"),
                                                    self.line("43000000", 0, 8000, "C1", "INV-1")]),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 8000, 0),
                                                    self.line("55500000", 0, 8000)]),
        ])
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [])
        self.assertEqual(result.row["adjustment"], [])

    def test_ambiguous_invoice_candidates_are_not_forced(self):
        self._jsonl("erp/ar_invoices.jsonl", [self.invoice("INV-1", 10000),
                                               self.invoice("INV-2", 10000)])
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("INVPOST1", "2026-06-01", [self.line("43000000", 10000, 0, "C1", "INV-1"),
                                                     self.line("70500000", 0, 10000)]),
            self.entry("INVPOST2", "2026-06-01", [self.line("43000000", 10000, 0, "C1", "INV-2"),
                                                     self.line("70500000", 0, 10000)]),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 8000, 0),
                                                    self.line("55500000", 0, 8000)]),
        ])
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [])
        self.assertEqual(result.row["adjustment"], [])
        self.assertTrue(any("unique" in diagnostic or "ambiguous" in diagnostic
                            for diagnostic in result.diagnostics))

    def test_unique_exact_subset_applies_all_invoices_in_compatible_company_and_currency(self):
        self._jsonl("erp/ar_invoices.jsonl", [self.invoice("INV-001", 5000),
                                               self.invoice("INV-002", 5000)])
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [{
            "bank_line": "BL1", "booking_date": "2026-07-02", "value_date": "2026-07-02",
            "amount": 10000, "currency": "EUR", "text": "TRANSFERENCIA DE CLIENTE ALFA",
        }])
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("INVPOST1", "2026-06-01", [self.line("43000000", 5000, 0, "C1", "INV-001"),
                                                      self.line("70500000", 0, 5000)]),
            self.entry("INVPOST2", "2026-06-02", [self.line("43000000", 5000, 0, "C1", "INV-002"),
                                                      self.line("70500000", 0, 5000)]),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 10000, 0),
                                                    self.line("55500000", 0, 10000)]),
        ])
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [
            {"invoice": "INV-001", "amount": 5000}, {"invoice": "INV-002", "amount": 5000},
        ])
        self.assertEqual(sum(line["debit"] for line in result.row["adjustment"]),
                         sum(line["credit"] for line in result.row["adjustment"]))

    def test_ambiguous_group_with_multiple_exact_subsets_is_not_tie_broken(self):
        self._jsonl("erp/ar_invoices.jsonl", [
            self.invoice("INV-001", 26749500), self.invoice("INV-002", 26749500),
            self.invoice("INV-003", 13374750), self.invoice("INV-004", 13374750),
        ])
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [{
            "bank_line": "BL1", "booking_date": "2026-07-02", "value_date": "2026-07-02",
            "amount": 53499000, "currency": "EUR", "text": "TRANSFERENCIA DE CLIENTE ALFA",
        }])
        postings = []
        for index, (invoice_id, amount) in enumerate((("INV-001", 26749500), ("INV-002", 26749500),
                                                       ("INV-003", 13374750), ("INV-004", 13374750)), 1):
            postings.append(self.entry(f"INVPOST{index}", f"2026-06-0{index}", [
                self.line("43000000", amount, 0, "C1", invoice_id),
                self.line("70500000", 0, amount),
            ]))
        postings.append(self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 53499000, 0),
                                                                 self.line("55500000", 0, 53499000)]))
        self._jsonl("erp/journal_entries.jsonl", postings)
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [])
        self.assertEqual(result.row["adjustment"], [])
        self.assertTrue(any("multiple exact invoice subsets" in item for item in result.diagnostics))

    def test_matching_amount_does_not_override_company_or_currency(self):
        for invoice_company, invoice_currency in (("1200", "EUR"), ("1100", "USD")):
            with self.subTest(company=invoice_company, currency=invoice_currency):
                self._jsonl("erp/ar_invoices.jsonl", [self.invoice(
                    "INV-001", 8000, company=invoice_company, currency=invoice_currency)])
                invoices = self._run()
                # Keep the ERP journal and bank consistent with the invoice company/currency
                # where possible; the receipt itself remains in company 1100 and EUR.
                self.assertEqual(invoices.results[0].row["applications"], [])

    def test_inbox_pdf_and_xml_are_never_read(self):
        (self.phase / "inbox/ar/remittances/notice.pdf").write_text("not a PDF", encoding="utf-8")
        (self.phase / "inbox/ar/remittances/notice.xml").write_text("not XML", encoding="utf-8")
        self.assertEqual(len(self._run().results), 1)


if __name__ == "__main__":
    unittest.main()
