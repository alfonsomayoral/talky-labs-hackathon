"""Independent attachment boundaries and complete-publication regressions."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import contextlib
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from billing_support import BillingCase
from kalmora.billing.io import write_billing_files
from kalmora.billing.model import BillingType
from kalmora.billing.observations import BillingObservations, adapt_billing_sources
from kalmora.documents.contracts import ParsedBlock, ParsedDocument
from kalmora.facts import DocumentFacts, Evidence, Fact
from kalmora.cli import main


class SourceAdaptationTests(BillingCase):
    def setUp(self):
        super().setUp()
        self.tables["companies"][0]["currency"] = "EUR"
        self.item_value = self.item(BillingType.SERVICE_MONTHLY)

    def source(self, name, values, counts):
        path = f"inbox/ar/billing/B1/{name}"
        text = "\n".join(f"{key}: {value}" for key, value in values.items())
        digest = sha256(text.encode()).hexdigest()
        document = ParsedDocument(path, digest, "text/plain", "source-test-v1",
                                  (ParsedBlock("source", text),))
        facts = DocumentFacts(digest, "normalized-test-v1", {
            key: [Fact(value, Evidence(path, "source", quote=f"{key}: {value}"))]
            for key, value in values.items()})
        return BillingObservations(BillingType.SERVICE_MONTHLY, facts, counts), document

    def complete(self, name="service.txt", canon=10000):
        return self.source(name, {"currency": "EUR", "month": "2026-07",
            "canon_cents": canon, "canon_status_text": "Conforme",
            "authority_text": "Técnico municipal"}, {"extra": 0})

    def test_complementary_headers_keep_both_originals(self):
        first = self.source("period.txt", {"currency": "EUR", "month": "2026-07"}, {})
        second = self.source("acceptance.txt", {"canon_cents": 10000,
            "canon_status_text": "Conforme", "authority_text": "Técnico municipal"}, {"extra": 0})
        result = adapt_billing_sources(self.data(), self.item_value, (first, second))
        self.assertEqual(result.facts.canon, 10000)
        self.assertEqual({e.document for e in result.facts.evidence}, {first[1].path, second[1].path})

    def test_conflicting_amounts_preserve_candidates_and_block(self):
        result = adapt_billing_sources(self.data(), self.item_value,
                                      (self.complete(), self.complete("other.txt", 12000)))
        self.assertIsNone(result.facts)
        self.assertEqual(result.diagnostics[0].code, "CONFLICT")
        self.assertEqual({fact.value for fact in result.diagnostics[0].candidates}, {10000, 12000})

    def test_source_identity_and_table_coverage_do_not_merge_silently(self):
        observed, document = self.complete()
        foreign = replace(document, path="inbox/ar/billing/OTHER/service.txt")
        result = adapt_billing_sources(self.data(), self.item_value, ((observed, foreign),))
        self.assertEqual(result.diagnostics[0].code, "SOURCE_MISMATCH")
        altered = replace(observed, row_counts={"extra": 1})
        result = adapt_billing_sources(self.data(), self.item_value,
                                      ((observed, document), (altered, document)))
        self.assertEqual(result.diagnostics[0].code, "CONFLICTING_TABLE_COVERAGE")

    def test_failed_validation_keeps_prior_delivery_bytes(self):
        output = self.root / "out/ar_billing.jsonl"
        output.parent.mkdir()
        output.write_text("previous billing")
        output.with_name("pending_wip.jsonl").write_text("previous WIP")
        unresolved = self.run_item(self.cert(current=1))
        with self.assertRaises(ValueError):
            write_billing_files(unresolved, output)
        self.assertEqual(output.read_text(), "previous billing")
        self.assertEqual(output.with_name("pending_wip.jsonl").read_text(), "previous WIP")

    def test_cli_refuses_recordings_inside_original_phase_before_writes(self):
        with contextlib.redirect_stderr(io.StringIO()):
            status = main(["solve-ar-billing", str(self.root), "--output", str(self.root.parent / "delivery.jsonl"),
                           "--work-dir", str(self.root / "state")])
        self.assertEqual(status, 1)
        self.assertFalse((self.root / "state").exists())

    def test_failed_second_publication_restores_prior_pending_wip(self):
        output = self.root / "delivery/ar_billing.jsonl"
        output.parent.mkdir()
        pending = output.with_name("pending_wip.jsonl")
        output.write_text("previous billing")
        pending.write_text("previous WIP")
        replace_file = os.replace

        def fail_invoice(source, destination):
            if Path(destination).resolve() == output.resolve():
                raise OSError("simulated second publication failure")
            return replace_file(source, destination)

        with patch("kalmora.billing.io.os.replace", side_effect=fail_invoice):
            with self.assertRaises(OSError):
                write_billing_files(self.run_item(self.cert()), output)
        self.assertEqual(output.read_text(), "previous billing")
        self.assertEqual(pending.read_text(), "previous WIP")

    def test_close_refuses_delivery_symlink_into_original_phase(self):
        from kalmora.closing import _ar_billing
        original = self.root / "original.jsonl"
        original.write_text("original input")
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "ar_billing.jsonl"
            destination.symlink_to(original)
            with self.assertRaisesRegex(ValueError, "original phase"):
                _ar_billing(self.root, destination, Path(tmp) / "state", [])
            self.assertFalse((Path(tmp) / "state").exists())
        self.assertEqual(original.read_text(), "original input")


if __name__ == "__main__":
    unittest.main()
