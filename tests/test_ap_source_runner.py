"""Original-task/source composition without accounting defaults or provider calls."""
from dataclasses import replace
import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalmora.ap_sources import classify_ap_source, prepare_ap_sources
from kalmora.cli import main
from kalmora.documents.contracts import ParsedBlock, ParsedDocument, digest
from kalmora.documents.replay import RecordedExtractor, RecordingConfig, RecordingStore, ExtractionCapture
from kalmora.documents.router import DocumentRouter
from kalmora.documents.xml_extractor import XMLDocumentExtractor
from kalmora.facts import DocumentFacts, Evidence, Fact

XML = '''<Facturae><FileHeader><SchemaVersion>3.2.2</SchemaVersion></FileHeader>
<Invoices><Invoice><InvoiceHeader><InvoiceClass>OR</InvoiceClass><InvoiceNumber>N-NEW</InvoiceNumber></InvoiceHeader>
<InvoiceIssueData><IssueDate>2031-11-02</IssueDate><InvoiceCurrencyCode>EUR</InvoiceCurrencyCode></InvoiceIssueData>
<InvoiceTotals><TotalGrossAmountBeforeTaxes>10.00</TotalGrossAmountBeforeTaxes><TotalTaxOutputs>2.10</TotalTaxOutputs>
<TotalTaxesWithheld>0.00</TotalTaxesWithheld><InvoiceTotal>12.10</InvoiceTotal></InvoiceTotals>
</Invoice></Invoices></Facturae>'''


class APSourceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.phase, self.out = self.root / "phase", self.root / "state"
        (self.phase / "tasks").mkdir(parents=True)
        (self.phase / "tasks" / "close.json").write_text(json.dumps(dict(month="2031-11")))
        self.ids = ("OPAQUE-NEW",)
        self.tasks(self.ids)
        self.source("OPAQUE-NEW", {"source.xml": XML})

    def tasks(self, ids):
        (self.phase / "tasks" / "ap_documents.json").write_text(json.dumps(list(ids)))

    def source(self, doc_id, files, declared=None):
        folder = self.phase / "inbox" / "ap" / doc_id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "message.json").write_text(json.dumps(dict(doc_id=doc_id, channel="facturae",
            received_at="2031-11-08T10:00:00", attachments=list(files) if declared is None else declared)))
        for name, content in files.items():
            (folder / name).write_text(content)

    def artifact(self, result, packet=0, attachment=0):
        path = result.manifest["documents"][packet]["attachments"][attachment]["artifact"]
        return json.loads((result.manifest_path.parent / path).read_text())

    async def test_supported_xml_and_metadata_are_direct_normalized_and_agnostic_to_task_ids(self):
        with patch("socket.create_connection", side_effect=AssertionError("no provider/network")):
            result = await prepare_ap_sources(self.phase, self.out)
        self.assertEqual(result.manifest["month"], "2031-11")
        self.assertEqual(result.manifest["report"], dict(task_count=1, attachment_count=1,
            incomplete_tasks=0, deterministic_xml=1, unknown_sources=0, new_provider_calls=0, new_provider_cost_usd="0"))
        self.assertFalse(result.manifest["accounting_run"])
        packet, = result.manifest["documents"]
        self.assertEqual(packet["doc_id"], "OPAQUE-NEW")
        metadata = DocumentFacts.from_dict(packet["metadata"])
        self.assertEqual(metadata.fields["received_at"][0].value, "2031-11-08T10:00:00")
        artifact = self.artifact(result)
        facts = DocumentFacts.from_dict(artifact["normalized"])
        self.assertEqual(facts.fields["gross_cents"][0].value, 1210)
        self.assertEqual(artifact["classification"]["document_type"], "CREDIT_NOTE")
        self.assertEqual(artifact["classification"]["evidence"][0]["value"], "OR")
        self.assertNotIn("decision", artifact)
        self.assertNotIn("journal_entry", artifact)

    async def test_original_message_fields_are_preserved_for_identity_and_chronology(self):
        path = self.phase / "inbox" / "ap" / "OPAQUE-NEW" / "message.json"
        message = json.loads(path.read_text())
        message.update({"from": "billing@example.test", "uploaded_by": "uploader@example.test",
                        "subject": "Original source subject", "body": "Original source body"})
        path.write_text(json.dumps(message))
        result = await prepare_ap_sources(self.phase, self.out)
        metadata = DocumentFacts.from_dict(result.manifest["documents"][0]["metadata"])
        for key in message:
            self.assertEqual(metadata.fields[key][0].value, message[key])
            self.assertEqual(metadata.fields[key][0].evidence.document, "inbox/ap/OPAQUE-NEW/message.json")

    async def test_every_attachment_is_retained_and_uninterpreted_sources_do_not_become_not_invoice(self):
        self.source("OPAQUE-NEW", {"source.xml": XML, "dua.txt": "Customs invoice VAT 9.00", "hours.txt": "Work hours"},
                    declared=["source.xml", "missing.pdf"])
        result = await prepare_ap_sources(self.phase, self.out)
        packet, = result.manifest["documents"]
        self.assertEqual(len(packet["attachments"]), 3)
        self.assertIn("MISSING_ATTACHMENT:missing.pdf", packet["diagnostics"])
        self.assertIn("UNLISTED_ATTACHMENT:hours.txt", packet["diagnostics"])
        self.assertEqual(result.manifest["report"]["unknown_sources"], 2)
        self.assertEqual(result.manifest["report"]["incomplete_tasks"], 1)
        stage = self.artifact(result)
        self.assertEqual((stage["status"], stage["error"], stage["classification"]),
                         ("UNKNOWN", "RESIDUAL_EXTRACTION_REQUIRED", None))

    async def test_equal_attachment_bytes_preserve_each_source_origin_and_packet(self):
        self.tasks(["OPAQUE-NEW", "DIFFERENT-ID"])
        self.source("DIFFERENT-ID", {"source.xml": XML})
        result = await prepare_ap_sources(self.phase, self.out)
        first, second = self.artifact(result), self.artifact(result, packet=1)
        self.assertEqual(first["source_sha256"], second["source_sha256"])
        a, b = DocumentFacts.from_dict(first["raw"]), DocumentFacts.from_dict(second["raw"])
        self.assertNotEqual(a.fields["document_number"][0].evidence.document,
                            b.fields["document_number"][0].evidence.document)
        self.assertNotEqual(result.manifest["documents"][0]["attachments"][0]["artifact"],
                            result.manifest["documents"][1]["attachments"][0]["artifact"])

    async def test_literal_title_and_xml_class_conflicts_are_preserved_and_copy_is_not_duplicate(self):
        parsed = DocumentRouter(self.phase).parse("inbox/ap/OPAQUE-NEW/source.xml")
        facts = await XMLDocumentExtractor().extract(parsed)
        conflict = replace(facts, fields=dict(facts.fields, document_type_hint=[Fact(
            "INVOICE", Evidence(parsed.path, "title", quote="INVOICE"))]))
        self.assertEqual(classify_ap_source(conflict).status, "CONFLICT")
        copied = replace(facts, fields=dict(facts.fields, **{"raw.invoice_class": [replace(
            facts.fields["raw.invoice_class"][0], value="CO")]}))
        self.assertEqual(classify_ap_source(copied).document_type, "INVOICE")

    async def test_fixture_source_replay_has_stable_packets_without_provider_callbacks(self):
        self.source("OPAQUE-NEW", {"source.xml": XML, "invoice.txt": "Invoice F-NEW total 12.34"})
        parsed = DocumentRouter(self.phase).parse("inbox/ap/OPAQUE-NEW/invoice.txt")
        facts = DocumentFacts(parsed.source_sha256, "fixture-extractor", {
            "document_type_hint": [Fact("Invoice", Evidence(parsed.path, "text", quote="Invoice"))],
            "gross": [Fact("12.34", Evidence(parsed.path, "text", quote="12.34"))]})
        config = RecordingConfig("fixture", "fixture-model", "fixture-extractor", "prompt-v1",
                                 "a" * 64, "schema-v1", "b" * 64)
        store = RecordingStore(self.root / "captures")
        store.save("extract", parsed, config, ExtractionCapture(facts, {}, {}), origin="synthetic")
        a = RecordedExtractor(store, config, mode="fixture")
        with patch("socket.create_connection", side_effect=AssertionError("provider disabled")):
            first = await prepare_ap_sources(self.phase, self.out, mode="fixture", extractor=a)
            second = await prepare_ap_sources(self.phase, self.root / "repeat", mode="fixture",
                extractor=RecordedExtractor(store, config, mode="fixture"))
        self.assertEqual(first.stable_sha256, second.stable_sha256)
        self.assertEqual(first.manifest["documents"], second.manifest["documents"])
        self.assertEqual((a.capture_calls, a.cache_hits), (0, 1))
        self.assertEqual(first.manifest["report"]["new_provider_calls"], 0)
        rejected = await prepare_ap_sources(self.phase, self.root / "real-replay", mode="replay",
            extractor=RecordedExtractor(store, config, mode="replay"))
        self.assertEqual(rejected.manifest["report"]["unknown_sources"], 1)

    async def test_all_original_pages_are_retained_and_a_transform_cannot_drop_a_page(self):
        self.source("OPAQUE-NEW", {"scanned.pdf": "synthetic source bytes"})
        path = "inbox/ap/OPAQUE-NEW/scanned.pdf"
        parsed = ParsedDocument(path, digest(b"synthetic source bytes"), "application/pdf", "synthetic-parser",
                                (ParsedBlock("P1", "page one", 1), ParsedBlock("P2", "page two", 2)))
        with patch.object(DocumentRouter, "parse", return_value=parsed):
            first = await prepare_ap_sources(self.phase, self.out)
            bad = await prepare_ap_sources(self.phase, self.root / "bad", transform=lambda d: replace(d, blocks=d.blocks[:1]))
        self.assertEqual(len(self.artifact(first)["parsed"]["blocks"]), 2)
        self.assertEqual(self.artifact(bad)["error"], "INVALID_SOURCE_STAGE")
        self.assertEqual(bad.manifest["report"]["new_provider_calls"], 0)

    async def test_changed_original_and_task_inventory_fail_before_publishing_the_phase_manifest(self):
        original = XMLDocumentExtractor.extract
        async def mutate(extractor, parsed):
            result = await original(extractor, parsed)
            self.tasks(["DIFFERENT-ID"])
            return result
        with patch.object(XMLDocumentExtractor, "extract", mutate):
            with self.assertRaisesRegex(ValueError, "task inventory changed"):
                await prepare_ap_sources(self.phase, self.out)
        self.assertFalse((self.out / "phase-sources.json").exists())

    async def test_source_destination_golden_and_message_identity_are_guarded(self):
        with self.assertRaisesRegex(ValueError, "outside the original"):
            await prepare_ap_sources(self.phase, self.phase / "state")
        with self.assertRaisesRegex(ValueError, "golden"):
            await prepare_ap_sources(self.phase / "golden", self.out)
        message = self.phase / "inbox" / "ap" / "OPAQUE-NEW" / "message.json"
        payload = json.loads(message.read_text())
        message.write_text(json.dumps(dict(payload, doc_id="WRONG")))
        with self.assertRaisesRegex(ValueError, "message identity"):
            await prepare_ap_sources(self.phase, self.out)

    async def test_output_subdirectory_symlink_cannot_write_source_artifacts_into_originals(self):
        self.out.mkdir()
        (self.out / "sources").symlink_to(self.phase)
        original_files = sorted(str(p.relative_to(self.phase)) for p in self.phase.rglob("*") if p.is_file())
        with self.assertRaisesRegex(ValueError, "artifact path escapes"):
            await prepare_ap_sources(self.phase, self.out)
        self.assertEqual(original_files, sorted(str(p.relative_to(self.phase)) for p in self.phase.rglob("*") if p.is_file()))

    async def test_message_without_document_source_is_incomplete_and_cli_returns_nonzero(self):
        (self.phase / "inbox" / "ap" / "OPAQUE-NEW" / "source.xml").unlink()
        self.source("OPAQUE-NEW", {})
        result = await prepare_ap_sources(self.phase, self.out)
        self.assertEqual(result.manifest["report"]["incomplete_tasks"], 1)
        self.assertIn("MISSING_DOCUMENT_SOURCE", result.manifest["documents"][0]["diagnostics"])
        self.assertEqual(result.manifest["documents"][0]["attachments"], [])
        import asyncio
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status = await asyncio.to_thread(main, ["--run-dir", str(self.root / "reports"), "prepare-ap",
                str(self.phase), "--state-dir", str(self.out)])
        self.assertEqual(status, 1)

    async def test_cli_cannot_write_run_reports_inside_golden(self):
        import asyncio
        report_dir = self.root / "external" / "golden"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            status = await asyncio.to_thread(main, ["--run-dir", str(report_dir), "prepare-ap",
                str(self.phase), "--state-dir", str(self.out)])
        self.assertEqual(status, 1)
        self.assertFalse(report_dir.exists())

    async def test_cli_deterministic_preparation_and_missing_budget_fail_before_provider(self):
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            # CLI owns its event loop; execute it outside this async loop.
            import asyncio
            status = await asyncio.to_thread(main, ["--run-dir", str(self.root / "reports"), "prepare-ap",
                str(self.phase), "--state-dir", str(self.out)])
        self.assertEqual(status, 0)
        self.assertFalse(json.loads(output.getvalue())["accounting_run"])
        config = self.root / "settings.json"
        config.write_text("{}")
        with contextlib.redirect_stderr(error), patch("socket.create_connection", side_effect=AssertionError("no provider")):
            status = await asyncio.to_thread(main, ["--run-dir", str(self.root / "reports"), "prepare-ap",
                str(self.phase), "--state-dir", str(self.out), "--mode", "record", "--config", str(config),
                "--captures", str(self.root / "captures")])
        self.assertEqual(status, 1)
        self.assertIn("explicitly authorized --budget-usd", error.getvalue())

    async def test_authorized_record_cli_uses_actual_client_and_direct_xml_needs_no_calls(self):
        import asyncio
        config = self.root / "settings.json"
        config.write_text(json.dumps({"model": "gpt-6-luna", "input_rate": "0.00000025",
            "output_rate": "0.00000075", "pricing_provenance": "synthetic test ceiling",
            "timeout_seconds": None, "max_output_tokens": None}))
        output, error = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error), patch(
                "kalmora.llm.client.AsyncLLMClient.complete", side_effect=AssertionError("direct XML cannot call provider")):
            code = await asyncio.to_thread(main, ["--run-dir", str(self.root / "reports"), "prepare-ap",
                str(self.phase), "--state-dir", str(self.out), "--mode", "record", "--config", str(config),
                "--captures", str(self.root / "captures"), "--budget-usd", "5"])
        self.assertEqual(code, 0, error.getvalue())
        self.assertEqual(json.loads(output.getvalue())["new_provider_calls"], 0)
        self.assertTrue((self.out / "residual-identity.json").exists())


if __name__ == "__main__":
    unittest.main()
