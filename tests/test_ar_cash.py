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

    def test_duplicate_history_is_scoped_to_company_and_currency(self):
        (self.phase / "bank/BIN-1200").mkdir(parents=True)
        self._json("tasks/ar_receipts.json", ["BL1", "BL2"])
        self._jsonl("erp/bank_accounts.jsonl", [
            {"id": "BIN-1100", "company": "1100", "currency": "EUR", "gl_account": "57200001"},
            {"id": "BIN-1200", "company": "1200", "currency": "EUR", "gl_account": "57200002"},
        ])
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("INVPOST", "2026-06-01", [self.line("43000000", 10000, 0, "C1", "INV-1"),
                                                     self.line("70500000", 0, 10000)]),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 10000, 0),
                                                     self.line("55500000", 0, 10000)]),
        ])
        line = {"booking_date": "2026-07-02", "value_date": "2026-07-02",
                "amount": 10000, "currency": "EUR", "text": "TRANSFERENCIA DE CLIENTE ALFA"}
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [dict(line, bank_line="BL1")])
        self._jsonl("bank/BIN-1200/2026-07.lines.jsonl", [dict(line, bank_line="BL2")])
        first, second = self._run().results
        self.assertEqual(first.row["applications"], [{"invoice": "INV-1", "amount": 10000}])
        self.assertEqual(second.row["residuals"], [])
        self.assertEqual(second.row["adjustment"], [])

    def test_historical_full_receipt_supports_duplicate_classification(self):
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("INVPOST", "2026-06-01", [self.line("43000000", 10000, 0, "C1", "INV-1"),
                                                     self.line("70500000", 0, 10000)]),
            dict(self.entry("PRIORCASH", "2026-07-01", [self.line("57200001", 10000, 0),
                                                          self.line("43000000", 0, 10000, "C1", "INV-1")]),
                 currency="EUR"),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 10000, 0),
                                                     self.line("55500000", 0, 10000)]),
        ])
        (self.phase / "bank/BIN-1100/2026-07.lines.jsonl").write_text(json.dumps({
            "bank_line": "BL1", "booking_date": "2026-07-02", "value_date": "2026-07-02",
            "amount": 10000, "currency": "EUR", "text": "TRANSFERENCIA DE CLIENTE ALFA",
        }) + "\n", encoding="utf-8")
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [])
        self.assertEqual(result.row["residuals"], [{"type": "OVERPAYMENT_DUPLICATE",
                                                      "invoice": "INV-1", "amount": 10000}])
        self.assertEqual(result.row["adjustment"][1]["account"], "43800000")

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

    def test_non_customer_guarantee_return_and_insurance_indemnity(self):
        cases = [
            ("DEVOLUCIÓN FIANZA PROVISIONAL OBRA", "56500000"),
            ("ABONO INDEMNIZACIÓN SINIESTRO PÓLIZA 123", "75900000"),
        ]
        for text, account in cases:
            with self.subTest(text=text):
                self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [{
                    "bank_line": "BL1", "booking_date": "2026-07-02", "value_date": "2026-07-02",
                    "amount": 8000, "currency": "EUR", "text": text,
                }])
                result = self._run().results[0]
                self.assertIsNone(result.row["customer"])
                self.assertEqual(result.row["residuals"], [{"type": "NON_CUSTOMER", "amount": 8000}])
                self.assertEqual(result.row["adjustment"][1]["account"], account)

    def test_social_security_narrative_is_not_classified_as_insurance_income(self):
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [{
            "bank_line": "BL1", "booking_date": "2026-07-02", "value_date": "2026-07-02",
            "amount": 8000, "currency": "EUR", "text": "DEVOLUCIÓN DE SEGUROS SOCIALES",
        }])
        result = self._run().results[0]
        self.assertIsNone(result.row["customer"])
        self.assertEqual(result.row["residuals"], [])
        self.assertEqual(result.row["adjustment"], [])

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

    def test_factored_receipt_requires_matching_document_currency(self):
        self._jsonl("erp/ar_invoices.jsonl", [self.invoice("INV-1", 8000, factored=True, currency="USD")])
        self._jsonl("erp/factoring_assignments.jsonl", [{
            "invoice": "INV-1", "date": "2026-06-10", "customer": "C1",
        }])
        self._jsonl("erp/journal_entries.jsonl", [])
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [])
        self.assertEqual(result.row["residuals"], [])
        self.assertEqual(result.row["adjustment"], [])

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

    def test_one_payable_cannot_be_netted_against_two_receipts(self):
        self.test_netting_against_same_counterparty_vendor_is_balanced()
        self._jsonl("erp/ar_invoices.jsonl", [self.invoice("INV-1", 10000),
            self.invoice("INV-2", 11000, date="2026-07-03", due="2026-07-03")])
        journal = [json.loads(line) for line in (self.phase / "erp/journal_entries.jsonl").read_text().splitlines()]
        journal.append(self.entry("INVPOST2", "2026-07-03", [
            self.line("43000000", 11000, 0, "C1", "INV-2"), self.line("70500000", 0, 11000)]))
        self._jsonl("erp/journal_entries.jsonl", journal)
        first = json.loads((self.phase / "bank/BIN-1100/2026-07.lines.jsonl").read_text())
        second = dict(first, bank_line="BL2", amount=9000, booking_date="2026-07-04", value_date="2026-07-04")
        self._json("tasks/ar_receipts.json", ["BL1", "BL2"])
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [first, second])
        run = self._run()
        self.assertEqual(run.results[0].row["residuals"][0]["type"], "NETTING_AP")
        self.assertEqual(run.results[1].row["residuals"], [])
        self.assertEqual(run.results[1].row["applications"], [{"invoice": "INV-2", "amount": 9000}])

    def _ap_delivery(self, received: str) -> list[dict]:
        """A payable posted by this month's AP delivery, received on ``received``."""
        self._jsonl("erp/vendors.jsonl", [{"id": "V1", "name": "Cliente Alfa, S.A.",
                                            "tax_id": "TAX1", "companies": ["1100"]}])
        self._jsonl("erp/journal_entries.jsonl", [
            self.entry("INVPOST", "2026-06-01", [self.line("43000000", 10000, 0, "C1", "INV-1"),
                                                    self.line("70500000", 0, 10000)]),
            self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 8000, 0),
                                                    self.line("55500000", 0, 8000)]),
        ])
        (self.phase / "inbox/ap/API1").mkdir(parents=True, exist_ok=True)
        self._json("inbox/ap/API1/message.json", {"received_at": f"{received}T09:00:00"})
        return self._ap_delivery_rows()

    @staticmethod
    def _ap_delivery_rows() -> list[dict]:
        return [{"doc_id": "API1", "decision": "POST", "company": "1100", "vendor_id": "V1",
                 "invoice_number": "AP-1", "currency": "EUR",
                 "journal_entry": {"company": "1100", "lines": [
                     {"account": "62300000", "debit": 2000, "credit": 0, "partner": None},
                     {"account": "41000000", "debit": 0, "credit": 2000, "partner": "V1"}]}}]

    def test_payable_posted_by_this_months_ap_delivery_supports_netting(self):
        ap = self._ap_delivery(received="2026-07-01")
        result = build_ar_cash(PhaseData(self.phase), ap=ap).results[0]
        self.assertEqual(result.row["applications"], [{"invoice": "INV-1", "amount": 10000}])
        self.assertEqual(result.row["residuals"], [{"type": "NETTING_AP", "invoice": "INV-1", "amount": 2000}])
        self.assertEqual(sum(line["debit"] for line in result.row["adjustment"]),
                         sum(line["credit"] for line in result.row["adjustment"]))

    def test_netting_with_a_short_payment_applies_cash_plus_payable_and_leaves_the_rest_open(self):
        ap = self._ap_delivery(received="2026-07-01")
        bank = json.loads((self.phase / "bank/BIN-1100/2026-07.lines.jsonl").read_text())
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [dict(bank, amount=5000)])
        journal = [json.loads(line) for line in (self.phase / "erp/journal_entries.jsonl").read_text().splitlines()]
        journal[1] = self.entry("CASHPOST", "2026-07-02", [self.line("57200001", 5000, 0), self.line("55500000", 0, 5000)])
        self._jsonl("erp/journal_entries.jsonl", journal)
        result = build_ar_cash(PhaseData(self.phase), ap=ap).results[0]
        self.assertEqual(result.row["applications"], [{"invoice": "INV-1", "amount": 7000}])
        self.assertEqual(result.row["residuals"], [{"type": "NETTING_AP", "invoice": "INV-1", "amount": 2000}])
        self.assertEqual(sum(line["debit"] for line in result.row["adjustment"]),
                         sum(line["credit"] for line in result.row["adjustment"]))

    def test_short_payment_netting_targets_the_invoice_due_on_the_receipt_date(self):
        self.test_netting_with_a_short_payment_applies_cash_plus_payable_and_leaves_the_rest_open()
        self._jsonl("erp/ar_invoices.jsonl", [self.invoice("OLD-1", 9000, date="2026-03-01", due="2026-03-01"),
                                              self.invoice("INV-1", 10000, date="2026-07-02", due="2026-07-02")])
        journal = [json.loads(line) for line in (self.phase / "erp/journal_entries.jsonl").read_text().splitlines()]
        journal.append(self.entry("OLDPOST", "2026-03-01", [self.line("43000000", 9000, 0, "C1", "OLD-1"),
                                                            self.line("70500000", 0, 9000)]))
        self._jsonl("erp/journal_entries.jsonl", journal)
        ap = self._ap_delivery_rows()
        result = build_ar_cash(PhaseData(self.phase), ap=ap).results[0]
        self.assertEqual(result.row["applications"], [{"invoice": "INV-1", "amount": 7000}])

    def test_a_historical_netting_entry_links_vendor_and_customer_despite_different_tax_ids(self):
        ap = self._ap_delivery(received="2026-07-01")
        self._jsonl("erp/vendors.jsonl", [{"id": "V1", "name": "Cliente Alfa, S.A.",
                                            "tax_id": "OTHER", "companies": ["1100"]}])
        journal = [json.loads(line) for line in (self.phase / "erp/journal_entries.jsonl").read_text().splitlines()]
        journal.append(self.entry("OLDNET", "2026-05-06", [
            self.line("57200001", 3000, 0), self.line("43000000", 0, 4000, "C1", "OLD-1"),
            self.line("41000000", 1000, 0, "V1", "AP-0")]))
        self._jsonl("erp/journal_entries.jsonl", journal)
        result = build_ar_cash(PhaseData(self.phase), ap=ap).results[0]
        self.assertEqual(result.row["residuals"], [{"type": "NETTING_AP", "invoice": "INV-1", "amount": 2000}])

    def test_payable_received_after_the_receipt_cannot_support_netting(self):
        ap = self._ap_delivery(received="2026-07-03")
        result = build_ar_cash(PhaseData(self.phase), ap=ap).results[0]
        self.assertEqual(result.row["residuals"], [])

    def test_conflicting_tax_ids_prevent_name_only_ap_netting(self):
        self.test_netting_against_same_counterparty_vendor_is_balanced()
        self._jsonl("erp/vendors.jsonl", [{"id": "V1", "name": "Cliente Alfa, S.A.",
                                            "tax_id": "OTHER", "companies": ["1100"]}])
        result = self._run().results[0]
        self.assertEqual(result.row["residuals"], [])
        self.assertEqual(result.row["applications"], [{"invoice": "INV-1", "amount": 8000}])

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

    def test_matured_note_cannot_be_consumed_by_two_receipts(self):
        self.test_matured_promissory_note_is_applied_to_431()
        first = json.loads((self.phase / "bank/BIN-1100/2026-07.lines.jsonl").read_text())
        second = dict(first, bank_line="BL2", booking_date="2026-07-03", value_date="2026-07-03")
        self._json("tasks/ar_receipts.json", ["BL1", "BL2"])
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [first, second])
        run = self._run()
        self.assertEqual(run.results[0].row["applications"], [{"pagare": "7654321", "amount": 8000}])
        self.assertEqual(run.results[1].row["applications"], [])
        self.assertEqual(run.results[1].row["adjustment"], [])

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

    def _open_invoices(self, invoices, amount):
        """Post each (id, payable, date) as an open receivable and receive ``amount`` on 2026-07-02."""
        self._jsonl("erp/ar_invoices.jsonl", [self.invoice(i, p, date=d, due=d) for i, p, d in invoices])
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [{
            "bank_line": "BL1", "booking_date": "2026-07-02", "value_date": "2026-07-02",
            "amount": amount, "currency": "EUR", "text": "TRANSFERENCIA DE CLIENTE ALFA",
        }])
        postings = [self.entry(f"INVPOST{n}", d, [self.line("43000000", p, 0, "C1", i),
                                                  self.line("70500000", 0, p)])
                    for n, (i, p, d) in enumerate(invoices, 1)]
        postings.append(self.entry("CASHPOST", "2026-07-02", [self.line("57200001", amount, 0),
                                                                 self.line("55500000", 0, amount)]))
        self._jsonl("erp/journal_entries.jsonl", postings)

    def test_invoice_issued_by_this_months_billing_can_be_applied(self):
        self._jsonl("erp/ar_invoices.jsonl", [])
        self._jsonl("erp/journal_entries.jsonl", [self.entry("CASHPOST", "2026-07-20", [
            self.line("57200001", 8000, 0), self.line("55500000", 0, 8000)])])
        self._jsonl("bank/BIN-1100/2026-07.lines.jsonl", [{
            "bank_line": "BL1", "booking_date": "2026-07-20", "value_date": "2026-07-20",
            "amount": 8000, "currency": "EUR", "text": "TRANSFERENCIA DE CLIENTE ALFA EN26-00013",
        }])
        billed = {"billing_item": "BILL-X", "expected": "INVOICE",
                  "invoice": {"number": "EN26-00013", "date": "2026-07-03", "due_date": "2026-07-18",
                              "payable": 8000, "currency": "EUR"},
                  "journal_entry": {"company": "1100", "posting_date": "2026-07-03", "currency": "EUR",
                                    "lines": [self.line("43000000", 8000, 0, "C1", "EN26-00013"),
                                              self.line("70530000", 0, 8000)]}}
        result = build_ar_cash(PhaseData(self.phase), billing=[billed]).results[0]
        self.assertEqual(result.row["applications"], [{"invoice": "EN26-00013", "amount": 8000}])

    def test_smallest_exact_group_wins_over_larger_combinations(self):
        self._open_invoices([("INV-001", 26749500, "2026-06-01"), ("INV-002", 26749500, "2026-06-02"),
                             ("INV-003", 13374750, "2026-06-03"), ("INV-004", 13374750, "2026-06-04")],
                            53499000)
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [
            {"invoice": "INV-001", "amount": 26749500}, {"invoice": "INV-002", "amount": 26749500},
        ])

    def test_equal_size_groups_prefer_the_oldest_invoices(self):
        self._open_invoices([("SU-43", 386348, "2026-03-04"), ("SU-44", 7448758, "2026-03-31"),
                             ("SU-62", 7448758, "2026-04-30"), ("SU-79", 7448758, "2026-05-31")],
                            386348 + 2 * 7448758)
        result = self._run().results[0]
        self.assertEqual(sorted(app["invoice"] for app in result.row["applications"]),
                         ["SU-43", "SU-44", "SU-62"])
        self.assertTrue(any(item.startswith("tie-break: 3 groups of 3") for item in result.diagnostics))

    def test_partial_payment_by_ratio_applies_to_the_oldest_matching_open_invoice(self):
        self._open_invoices([("SU-23", 17271972, "2026-02-28"), ("SU-30", 9000000, "2026-03-31"),
                             ("SU-40", 9100000, "2026-04-30")], 12953979)
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [{"invoice": "SU-23", "amount": 12953979}])
        self.assertIn("partial payment by ratio 0.75; the rest stays open", result.diagnostics)
        self.assertEqual(result.row["adjustment"][0], {"company": "1100", "account": "55500000",
                                                       "debit": 12953979, "credit": 0})

    def test_partial_ratio_truncates_to_the_cent(self):
        self._open_invoices([("OB-25", 51500000, "2026-03-31"), ("OB-34", 36039724, "2026-04-30")],
                            14415889)
        result = self._run().results[0]
        self.assertEqual(result.row["applications"], [{"invoice": "OB-34", "amount": 14415889}])

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
