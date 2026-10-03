"""Synthetic duplicate/reissue variants, independent from golden answers."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest

from kalmora.ap_duplicates import (duplicate_result, normalize_number,
                                   registered_duplicate_records)
from kalmora.data import PhaseData
from kalmora.facts import Evidence
from kalmora.model.ap_duplicate_record import DuplicateRecord

PROOF = (Evidence("synthetic-invoice", "identity_and_amount"),)


def record(id="A", **kwargs):
    values = dict(company="1100", vendor="V1", currency="EUR", number="2026-0001",
                  received_at="2026-07-01T10:00:00", amount_cents=12100,
                  evidence=PROOF, status="POST")
    values.update(kwargs)
    return DuplicateRecord(id, **values)


class DuplicateTests(unittest.TestCase):
    def test_separators_case_and_explicit_prefix_not_digit_guess(self):
        self.assertEqual(normalize_number(" fv-2026 / 0001 "), "FV20260001")
        self.assertEqual(normalize_number("Factura: 2026/0001", ["FACTURA:"]), "20260001")
        self.assertNotEqual(normalize_number("F00001"), normalize_number("00001"))
        self.assertNotEqual(normalize_number("2026-0001"), normalize_number("2026-001"))
        self.assertNotEqual(normalize_number("2026-0001-R"), normalize_number("2026-0001"))
        with self.assertRaises(ValueError):
            normalize_number("FAV20260001", ["F", "FAV"])
        with self.assertRaises(ValueError):
            normalize_number("/ - ")
        with self.assertRaises(ValueError):
            normalize_number("INV20260001", "INV")

    def test_first_received_document_stable_against_input_order(self):
        a, b = record("A"), record("B", received_at="2026-07-02T10:00:00", status="RECEIVED")
        current = record("C", received_at="2026-07-03T10:00:00", number="2026 / 0001")
        original = [b, a]
        result = duplicate_result(current, original)
        self.assertEqual(result.status, "DUPLICATE")
        self.assertEqual(result.duplicate_of, "A")
        self.assertEqual(result, duplicate_result(current, reversed(original)))
        self.assertEqual(original, [b, a])
        self.assertEqual(result.evidence, (*PROOF, *PROOF))

    def test_exact_receipt_tie_uses_document_id_date_only_stays_unknown(self):
        self.assertEqual(duplicate_result(record("B"), [record("A")]).duplicate_of, "A")
        self.assertEqual(duplicate_result(record("A"), [record("B")], inventory_complete=True).status, "CLEAR")
        result = duplicate_result(record("B"), [record("A", received_at="2026-07-01")], inventory_complete=True)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("A:RECEPTION_ORDER_UNKNOWN", result.diagnostics)
        self.assertEqual(duplicate_result(record("B"), [record("A", received_at="2026-07-01", amount_cents=12200)], inventory_complete=True).status, "CLEAR")

    def test_future_document_not_duplicate(self):
        self.assertEqual(duplicate_result(record(), [record("B", received_at="2026-07-02T10:00:00")], inventory_complete=True).status, "CLEAR")

    def test_historical_date_can_prove_prior_receipt(self):
        prior = record(received_at="2026-06-30")
        result = duplicate_result(record("B"), [prior])
        self.assertEqual(result.duplicate_of, "A")

    def test_explicit_rejected_correction_can_keep_same_amount(self):
        prior = record(status="REJECT", corrected_by="B", currency=None, amount_cents=None)
        current = record("B", received_at="2026-07-02T10:00:00")
        result = duplicate_result(current, [prior], inventory_complete=True)
        self.assertEqual(result.status, "REISSUE")
        self.assertEqual(result.reissue_of, "A")
        self.assertEqual(duplicate_result(replace(current, number="2026-NEW"), [prior], inventory_complete=True).status, "REISSUE")
        self.assertEqual(duplicate_result(current, [prior]).status, "UNKNOWN")
        self.assertEqual(duplicate_result(current, [replace(prior, corrected_by=None)], inventory_complete=True).status, "UNKNOWN")

    def test_posted_or_held_received_copy_is_duplicate(self):
        current = record("B", received_at="2026-07-02T10:00:00")
        for status in ("RECEIVED", "POST", "POST_PAYMENT_BLOCK", "HOLD"):
            self.assertEqual(duplicate_result(current, [record(status=status)]).duplicate_of, "A")

    def test_rejected_predecessor_not_root_for_unrelated_retry(self):
        rejected = record(status="REJECT", corrected_by="B")
        corrected = record("B", received_at="2026-07-02T10:00:00")
        current = record("C", received_at="2026-07-03T10:00:00")
        self.assertEqual(duplicate_result(current, [rejected, corrected]).duplicate_of, "B")
        self.assertEqual(duplicate_result(current, [replace(rejected, currency=None, amount_cents=None), corrected]).duplicate_of, "B")

    def test_duplicate_chain_returns_original_not_resend(self):
        original = record()
        resend = record("B", received_at="2026-07-02T10:00:00", status="DUPLICATE", duplicate_of="A")
        current = record("C", received_at="2026-07-03T10:00:00")
        self.assertEqual(duplicate_result(current, [resend, original]).duplicate_of, "A")
        self.assertEqual(duplicate_result(current, [resend], inventory_complete=True).status, "UNKNOWN")

    def test_recurring_months_and_different_numbers_are_distinct(self):
        current = record("B", received_at="2026-07-02T10:00:00", service_period="2026-07")
        previous_month = record(service_period="2026-06")
        self.assertEqual(duplicate_result(current, [previous_month], inventory_complete=True).status, "CLEAR")
        self.assertEqual(duplicate_result(current, [record(number="2026-0002")], inventory_complete=True).status, "CLEAR")
        self.assertEqual(duplicate_result(current, [record(amount_cents=12200)], inventory_complete=True).status, "CLEAR")
        self.assertEqual(duplicate_result(current, [record()], inventory_complete=True).status, "UNKNOWN")

    def test_scope_and_document_type_isolation(self):
        current = record("B", received_at="2026-07-02T10:00:00")
        for changes in (dict(company="1910"), dict(vendor="V2"), dict(currency="USD"), dict(document_type="CREDIT_NOTE")):
            self.assertEqual(duplicate_result(current, [record(**changes)], inventory_complete=True).status, "CLEAR")
        self.assertEqual(duplicate_result(current, [record(currency=None)], inventory_complete=True).status, "UNKNOWN")

    def test_missing_inventory_amount_status_and_conflicting_identity(self):
        current = record("B", received_at="2026-07-02T10:00:00")
        self.assertEqual(duplicate_result(current, []).status, "UNKNOWN")
        self.assertEqual(duplicate_result(current, [], inventory_complete=True).status, "CLEAR")
        for prior in (record(amount_cents=None), record(status=None), record(status="CANCELLED")):
            self.assertEqual(duplicate_result(current, [prior], inventory_complete=True).status, "UNKNOWN")
        with self.assertRaises(ValueError):
            duplicate_result(current, [record(), record(amount_cents=12000)])
        with self.assertRaises(ValueError):
            duplicate_result(current, [record(amount_cents=True)])
        self.assertEqual(duplicate_result(replace(current, amount_cents=None), []).status, "UNKNOWN")

    def test_earlier_unknown_prevents_false_original_selection(self):
        unknown = record("A", amount_cents=None)
        known = record("B", received_at="2026-07-02T10:00:00")
        current = record("C", received_at="2026-07-03T10:00:00")
        self.assertEqual(duplicate_result(current, [unknown, known]).status, "UNKNOWN")
        late_unknown = replace(unknown, received_at="2026-07-02T11:00:00")
        self.assertEqual(duplicate_result(current, [late_unknown, known]).duplicate_of, "B")

    def test_phase_join_does_not_borrow_correction_amount_or_vendor_currency(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "erp").mkdir()
            (root / "tasks").mkdir()
            (root / "tasks/close.json").write_text('{"month":"2026-07"}')
            logs = [dict(doc_id="A", company="1100", vendor="V1", kind="invoice", number="2026-0001",
                         received_on="2026-06-28", decision="REJECT", corrected_by="B", duplicate_of=None),
                    dict(doc_id="B", company="1100", vendor="V1", kind="invoice", number="2026-0001",
                         received_on="2026-06-30", decision="HOLD", corrected_by=None, duplicate_of=None)]
            invoice = dict(doc_id="B", company="1100", vendor="V1", kind="invoice", number="2026-0001",
                           received_on="2026-06-30", decision="POST", currency="EUR", gross=12100)
            (root / "erp/ap_document_log.json").write_text(json.dumps(logs))
            (root / "erp/ap_invoices.json").write_text(json.dumps([invoice]))
            data = PhaseData(root)
            a, b = registered_duplicate_records(data)
            self.assertIsNone(a.currency)
            self.assertIsNone(a.amount_cents)
            self.assertEqual(a.corrected_by, "B")
            self.assertEqual(b.amount_cents, 12100)
            self.assertEqual(b.status, "HOLD")
            self.assertEqual(data.table("ap_document_log"), logs)
            self.assertEqual(duplicate_result(b, [a], inventory_complete=True).status, "REISSUE")
