"""Month document/history binding for duplicates, with synthetic facts only."""
import json
from pathlib import Path
import tempfile
import unittest

from kalmora.ap_duplicate_sources import MonthDocument, month_duplicate_results
from kalmora.data import PhaseData
from kalmora.facts import DocumentFacts, Evidence, Fact

SHA = "a" * 64


def log(doc_id, number, received_on, decision="POST", corrected_by=None):
    return dict(doc_id=doc_id, company="1100", vendor="V1", kind="invoice", number=number,
                received_on=received_on, decision=decision, reasons=[], duplicate_of=None,
                corrected_by=corrected_by, journal_entry=None, resolved_on=None)


def document(doc_id, received_at, number="2606340", gross=12100, **fields):
    values = dict(document_number=number, gross_cents=gross, currency="EUR",
                  supplier_tax_id="B11111111", recipient_tax_id="B22222222")
    values.update(fields)
    facts = DocumentFacts(SHA, "synthetic", {
        name: [Fact(value, Evidence(f"{doc_id}.pdf", name))] for name, value in values.items()})
    return MonthDocument(doc_id, {"doc_id": doc_id, "received_at": received_at}, ((facts, "INVOICE"),))


class DuplicateSourceTests(unittest.TestCase):
    def results(self, documents, logs=(), invoices=()):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for area in ("erp", "tasks"):
                (root / area).mkdir()
            (root / "tasks/close.json").write_text('{"month":"2026-07"}')
            (root / "erp/companies.json").write_text(json.dumps([{"code": "1100", "tax_id": "B22222222"}]))
            (root / "erp/vendors.json").write_text(json.dumps([{"id": "V1", "tax_id": "B11111111"}]))
            (root / "erp/ap_document_log.json").write_text(json.dumps(list(logs)))
            (root / "erp/ap_invoices.json").write_text(json.dumps(list(invoices)))
            return month_duplicate_results(documents, PhaseData(root))

    def test_number_written_without_vendor_prefix_duplicates_history(self):
        prior = log("H1", "F26-06340", "2026-06-20")
        invoice = dict(prior, currency="EUR", gross=12100)
        result = self.results([document("M1", "2026-07-02T08:00:00", "26/06340")], [prior], [invoice])["M1"]
        self.assertEqual((result.status, result.duplicate_of), ("DUPLICATE", "H1"))

    def test_first_month_document_wins(self):
        results = self.results([document("M2", "2026-07-03T09:00:00", "2606340 "),
                                document("M1", "2026-07-02T09:00:00", period_start="2026-06-01", period_end="2026-06-30")])
        self.assertEqual(results["M1"].status, "CLEAR")
        self.assertEqual((results["M2"].status, results["M2"].duplicate_of), ("DUPLICATE", "M1"))

    def test_equal_monthly_instalments_are_not_duplicates(self):
        prior = log("H1", "ALQ-2026-06", "2026-06-02")
        invoice = dict(prior, currency="EUR", gross=12100)
        result = self.results([document("M1", "2026-07-02T08:00:00", "ALQ-2026-07")], [prior], [invoice])["M1"]
        self.assertEqual(result.status, "CLEAR")

    def test_rejected_original_corrected_by_reissue_is_not_duplicate(self):
        rejected = log("H1", "2606340", "2026-06-25", decision="REJECT", corrected_by="M1")
        result = self.results([document("M1", "2026-07-02T08:00:00")], [rejected])["M1"]
        self.assertEqual((result.status, result.reissue_of), ("REISSUE", "H1"))

    def test_unbound_month_document_keeps_inventory_unknown(self):
        unresolved = document("M2", "2026-07-03T09:00:00", supplier_tax_id="B99999999")
        results = self.results([document("M1", "2026-07-02T09:00:00"), unresolved])
        self.assertEqual(results["M2"].diagnostics, ("DUPLICATE_FACTS_UNBOUND",))
        self.assertEqual(results["M1"].status, "UNKNOWN")
