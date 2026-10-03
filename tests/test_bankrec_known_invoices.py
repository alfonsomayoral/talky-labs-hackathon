import json
from pathlib import Path
import tempfile
import unittest

from kalmora.bankrec.run import known_invoices
from kalmora.data import PhaseData


class KnownInvoiceTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.phase = Path(tmp.name)
        (self.phase / "erp").mkdir()
        (self.phase / "tasks").mkdir()
        (self.phase / "tasks/close.json").write_text(json.dumps({"month": "2026-07"}))
        (self.phase / "inbox/ap/API1").mkdir(parents=True)
        (self.phase / "erp/ap_invoices.jsonl").write_text(json.dumps(
            {"vendor": "V1", "number": "OLD-1", "decision": "POST"}) + "\n")
        (self.phase / "inbox/ap/API1/message.json").write_text(json.dumps(
            {"doc_id": "API1", "subject": "Factura 26-777", "attachments": []}))

    def test_history_and_inbox_are_known_without_ap_output(self):
        known = known_invoices(PhaseData(self.phase))
        self.assertTrue(known("V1", "OLD-1"))
        self.assertTrue(known("V1", "26-777"))
        self.assertFalse(known("V1", "26-999"))

    def test_with_ap_output_only_posted_invoices_count(self):
        ap = [{"vendor_id": "V1", "invoice_number": "26-777", "decision": "REJECT"},
              {"vendor_id": "V1", "invoice_number": "26-888", "decision": "POST"}]
        known = known_invoices(PhaseData(self.phase), ap)
        self.assertFalse(known("V1", "26-777"))
        self.assertTrue(known("V1", "26-888"))
        self.assertTrue(known("V1", "OLD-1"))


if __name__ == "__main__":
    unittest.main()
