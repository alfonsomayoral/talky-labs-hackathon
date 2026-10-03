"""CLI source audit cannot overwrite inputs or masquerade as an AP delivery."""
import asyncio
import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalmora.ap_sources import prepare_ap_sources
from kalmora.cli import main
from tests import test_ap_source_runner as source_fixtures


class APSourcePlanCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.phase = self.root / "phase"
        for directory in ("tasks", "erp", "inbox/ap/DIFFERENT-TASK"):
            (self.phase / directory).mkdir(parents=True)
        (self.phase / "tasks/close.json").write_text(json.dumps({"month": "2031-11"}))
        (self.phase / "tasks/ap_documents.json").write_text(json.dumps(["DIFFERENT-TASK"]))
        (self.phase / "inbox/ap/DIFFERENT-TASK/message.json").write_text(json.dumps({
            "doc_id": "DIFFERENT-TASK", "channel": "facturae", "received_at": "2031-11-10T09:30:00Z",
            "attachments": ["source.xml"]}))
        (self.phase / "inbox/ap/DIFFERENT-TASK/source.xml").write_text(source_fixtures.XML.replace(
            "<InvoiceClass>OR</InvoiceClass>", "<InvoiceClass>OO</InvoiceClass>"))
        for table in ("vendors", "purchase_orders", "goods_receipts", "ap_invoices", "ap_document_log", "journal_entries"):
            (self.phase / "erp" / (table + ".jsonl")).write_text("")
        (self.phase / "erp/companies.json").write_text(json.dumps([
            {"code": "1000", "country": "ES", "tax_id": "BUYER-ELSEWHERE"}]))
        prepared = asyncio.run(prepare_ap_sources(self.phase, self.root / "sources"))
        self.manifest = prepared.manifest_path

    def execute(self, output, *, reports=None, extra=()):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = main(["--run-dir", str(reports or self.root / "reports"), "plan-ap", str(self.phase),
                           "--sources", str(self.manifest), "--output", str(output), *extra])
        return status, out.getvalue(), err.getvalue()

    def test_audit_replay_without_provider_preserves_unknown_and_never_exports_ap(self):
        first, second = self.root / "plans/first.json", self.root / "plans/replay.json"
        with patch("socket.create_connection", side_effect=AssertionError("provider disabled")):
            code, stdout, _ = self.execute(first)
            repeated, _, _ = self.execute(second)
        self.assertEqual((code, repeated), (1, 1))
        a, b = json.loads(first.read_text()), json.loads(second.read_text())
        self.assertEqual(a["stable_plan_sha256"], b["stable_plan_sha256"])
        self.assertEqual(a["task_keys"], ["DIFFERENT-TASK"])
        self.assertIsNone(a["observed_receipt_cutoff"])
        self.assertFalse(a["run"]["accounting_run"])
        self.assertEqual(a["execution"]["new_provider_calls"], 0)
        self.assertEqual(a["summary"]["statuses"]["UNKNOWN"], 1)
        self.assertFalse(json.loads(stdout)["accounting_run"])
        self.assertFalse(list(self.root.rglob("ap.jsonl")))

    def test_protected_outputs_rejected_before_report_or_source_write(self):
        original = self.manifest.read_bytes()
        for output in (self.phase / "audit.json", self.manifest, self.root / "golden/audit.json"):
            reports = self.root / "never-created-reports"
            code, _, error = self.execute(output, reports=reports)
            self.assertEqual(code, 1)
            self.assertIn("outside original sources", error)
            self.assertFalse(reports.exists())
        self.assertEqual(self.manifest.read_bytes(), original)
        self.assertFalse((self.root / "golden").exists())

    def test_cutoff_is_optional_explicit_evidence_and_golden_cannot_supply_it(self):
        cutoff = self.root / "cutoff.json"
        cutoff.write_text(json.dumps({"value": "2031-11-20", "evidence": {
            "document": "operator/close-clock", "field": "receipt_cutoff", "quote": "2031-11-20"}}))
        output = self.root / "plans/with-cutoff.json"
        code, _, _ = self.execute(output, extra=("--receipt-cutoff-fact", str(cutoff)))
        self.assertEqual(code, 1)  # Incomplete source identity still remains UNKNOWN.
        self.assertEqual(json.loads(output.read_text())["observed_receipt_cutoff"]["value"], "2031-11-20")
        denied = self.root / "plans/denied.json"
        code, _, error = self.execute(denied, extra=("--receipt-cutoff-fact", str(self.root / "golden/clock.json")))
        self.assertEqual(code, 1)
        self.assertIn("cannot be loaded from Golden", error)
        self.assertFalse(denied.exists())


if __name__ == "__main__":
    unittest.main()
