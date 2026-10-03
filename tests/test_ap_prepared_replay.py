"""Verified prepared AP views preserve originals, failures and fixture identity."""
import asyncio
import base64
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalmora.ap_document_bridge import APDocumentBridge
from kalmora.ap_sources import load_prepared_ap_sources, prepare_ap_sources
from kalmora.documents.ap_sources import APAttachment, APMessage, APTaskSources
from kalmora.documents.contracts import digest, fingerprint
from kalmora.documents.ocr import PDFVisionConfig, PDFVisionProcessor
from kalmora.documents.replay import ExtractionCapture, RecordedExtractor, RecordingConfig, RecordingStore
from kalmora.documents.router import DocumentRouter
from kalmora.facts import DocumentFacts, Evidence, Fact, atomic_json


XML = '''<Facturae><FileHeader><SchemaVersion>3.2.2</SchemaVersion></FileHeader>
<Invoices><Invoice><InvoiceHeader><InvoiceClass>OO</InvoiceClass><InvoiceNumber>F-OTHER</InvoiceNumber></InvoiceHeader>
<InvoiceIssueData><IssueDate>2032-02-03</IssueDate><InvoiceCurrencyCode>EUR</InvoiceCurrencyCode></InvoiceIssueData>
<InvoiceTotals><TotalGrossAmountBeforeTaxes>10.00</TotalGrossAmountBeforeTaxes><TotalTaxOutputs>2.10</TotalTaxOutputs>
<TotalTaxesWithheld>0.00</TotalTaxesWithheld><InvoiceTotal>12.10</InvoiceTotal></InvoiceTotals>
</Invoice></Invoices></Facturae>'''


class APPreparedReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.phase, self.state = self.root / "phase", self.root / "prepared"
        (self.phase / "tasks").mkdir(parents=True)
        self.ids = ["OPAQUE-X", "OTHER-7"]
        (self.phase / "tasks/close.json").write_text('{"month":"2032-02"}')
        self.tasks(self.ids)
        for doc_id in self.ids:
            self.sources(doc_id, {"invoice.xml": XML})

    def tasks(self, ids):
        (self.phase / "tasks/ap_documents.json").write_text(json.dumps(ids))

    def sources(self, doc_id, attachments, declared=None):
        folder = self.phase / "inbox/ap" / doc_id
        folder.mkdir(parents=True, exist_ok=True)
        message = dict(doc_id=doc_id, channel="facturae", received_at="2032-02-04T10:00:00",
            attachments=list(attachments) if declared is None else declared,
            subject="Original subject", body="Original body", mailbox="AP",
            uploaded_by="uploader@example.test", **{"from": "billing@example.test", "to": "ap@example.test"})
        (folder / "message.json").write_text(json.dumps(message))
        for filename, content in attachments.items():
            (folder / filename).write_text(content)

    def prepare(self, **options):
        return asyncio.run(prepare_ap_sources(self.phase, self.state, **options))

    def write_manifest(self, manifest):
        stable = {key: manifest[key] for key in (
            "month", "task_sha256", "close_sha256", "configuration", "documents")}
        manifest["stable_source_sha256"] = fingerprint(stable)
        atomic_json(self.state / "phase-sources.json", manifest)

    def alter_artifact(self, run, mutate):
        manifest = deepcopy(run.manifest)
        stage = manifest["documents"][0]["attachments"][0]
        artifact = json.loads((self.state / stage["artifact"]).read_text())
        mutate(artifact)
        key = fingerprint(dict(config=manifest["configuration"], source=artifact))
        relative = "sources/" + key + ".json"
        path = self.state / relative
        atomic_json(path, artifact)
        stage["artifact"], stage["artifact_sha256"] = relative, digest(path.read_bytes())
        self.write_manifest(manifest)

    def load(self, run):
        return load_prepared_ap_sources(self.phase, run.manifest_path)

    def rendered_fixture(self):
        try:
            from pypdf import PdfWriter
            import PIL.Image
        except ImportError:
            self.skipTest("PDF vision requires the documents extra")
        config = PDFVisionConfig()
        if not all(Path(tool).is_file() for tool in (config.renderer, config.tesseract)):
            self.skipTest("default local renderer/OCR tools unavailable")
        (self.phase / "inbox/ap/OPAQUE-X/invoice.xml").unlink()
        self.sources("OPAQUE-X", {"scan.pdf": ""})
        relative = "inbox/ap/OPAQUE-X/scan.pdf"
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        writer.write(self.phase / relative)
        processor = PDFVisionProcessor(self.phase, config)
        rendered = processor.process(DocumentRouter(self.phase).parse(relative))
        recording = RecordingConfig("fixture", "fixture-model", "fixture-v1", "prompt-v1",
                                    "a" * 64, "schema-v1", "b" * 64)
        store = RecordingStore(self.root / "captures")
        raw = DocumentFacts(rendered.source_sha256, "fixture-v1", {})
        store.save("extract", rendered, recording,
                   ExtractionCapture(raw, {}, {}, unknowns=({"field": "document_type_hint"},)),
                   origin="synthetic")
        run = self.prepare(mode="fixture", extractor=RecordedExtractor(store, recording, mode="fixture"),
                           transform=processor.process)
        self.assertEqual(run.manifest["documents"][0]["attachments"][0]["status"], "ACCEPTED")
        return run, rendered

    @staticmethod
    def refresh_vision_identity(parsed):
        provenance = [aid["provenance"] for aid in parsed["unverified_processing_aids"]]
        identity = fingerprint(dict(config=provenance[0]["config"], aids=provenance))
        parsed["parser_version"] = parsed["parser_version"].split("/pdf-vision-v2:")[0] + "/pdf-vision-v2:" + identity

    def test_default_rendered_pdf_replays_complete_view_without_provider_or_capture_adapter(self):
        run, rendered = self.rendered_fixture()
        with patch("socket.socket", side_effect=AssertionError("network disabled")), \
                patch.object(RecordedExtractor, "__init__", side_effect=AssertionError("no capture adapter")):
            loaded = self.load(run)
        attachment, = loaded["OPAQUE-X"].attachments
        self.assertEqual(attachment.document, rendered)
        self.assertIsNone(attachment.error)
        self.assertEqual(attachment.facts.fields, {})
        self.assertEqual(attachment.unknowns, ({"field": "document_type_hint"},))
        self.assertEqual(loaded["OTHER-7"].attachments[0].classification.document_type, "INVOICE")

    def test_rehashed_rendered_images_aids_provenance_and_warnings_are_authenticated(self):
        run, _ = self.rendered_fixture()
        from PIL import Image
        def image_mutation(parsed):
            saved = parsed["images"][0]
            with Image.open(BytesIO(base64.b64decode(saved["base64"]))) as original:
                image = original.convert("RGB")
            image.putpixel((0, 0), (0, 0, 0))
            stream = BytesIO()
            image.save(stream, "PNG")
            data = stream.getvalue()
            saved.update(base64=base64.b64encode(data).decode("ascii"), sha256=digest(data))
            parsed["unverified_processing_aids"][0]["provenance"]["image_sha256"] = digest(data)
        def aid_mutation(parsed):
            aid = parsed["unverified_processing_aids"][0]
            aid["text"] = "Invented OCR text"
            aid["provenance"]["text_sha256"] = digest(aid["text"].encode())
        def provenance_mutation(parsed):
            parsed["unverified_processing_aids"][0]["provenance"]["authoritative"] = True
        def warnings_mutation(parsed):
            parsed["warnings"].append("invented:source_verified")
        for name, mutate in (("image", image_mutation), ("aid", aid_mutation),
                             ("provenance", provenance_mutation), ("warnings", warnings_mutation)):
            with self.subTest(field=name):
                def alter(artifact):
                    mutate(artifact["parsed"])
                    self.refresh_vision_identity(artifact["parsed"])
                self.alter_artifact(run, alter)
                with self.assertRaisesRegex(ValueError, "original blocks/pages/parser"):
                    self.load(run)

    def test_custom_pdf_vision_tools_and_unsupported_transform_are_never_executed(self):
        run, _ = self.rendered_fixture()
        def custom(artifact):
            parsed = artifact["parsed"]
            parsed["unverified_processing_aids"][0]["provenance"]["config"]["renderer"] = "/saved/arbitrary/program"
            self.refresh_vision_identity(parsed)
        self.alter_artifact(run, custom)
        with patch.object(PDFVisionProcessor, "process", side_effect=AssertionError("saved tools must not execute")):
            with self.assertRaisesRegex(ValueError, "current local default configuration"):
                self.load(run)
        def old_transform(artifact):
            artifact["parsed"]["parser_version"] = artifact["parsed"]["parser_version"].replace(
                "/pdf-vision-v2:", "/pdf-vision-v1:")
        self.alter_artifact(run, old_transform)
        with patch.object(PDFVisionProcessor, "process", side_effect=AssertionError("unsupported transform must not execute")):
            with self.assertRaisesRegex(ValueError, "original blocks/pages/parser"):
                self.load(run)

    def test_original_xml_returns_stable_public_typed_views_without_provider_or_extraction(self):
        run = self.prepare()
        with patch("socket.socket", side_effect=AssertionError("network disabled")), \
                patch.object(RecordedExtractor, "__init__", side_effect=AssertionError("no capture adapter")), \
                patch("kalmora.documents.xml_extractor.XMLDocumentExtractor.extract",
                      side_effect=AssertionError("load saved facts only")):
            first, second = self.load(run), self.load(run)
        self.assertEqual(first, second)
        self.assertEqual(list(first), self.ids)
        self.assertEqual(first.source_mode, "deterministic")
        self.assertEqual(first.stable_source_sha256, run.stable_sha256)
        task = first["OPAQUE-X"]
        self.assertIsInstance(task, APTaskSources)
        self.assertIsInstance(task.message, APMessage)
        attachment, = task.attachments
        self.assertIsInstance(attachment, APAttachment)
        self.assertEqual(attachment.normalized.facts.fields["payable_cents"][0].value, 1210)
        self.assertEqual(attachment.classification.document_type, "INVOICE")
        self.assertEqual(APDocumentBridge.from_task_sources(task).classification.document_type, "INVOICE")
        original_message = json.loads((self.phase / task.message.path).read_text())
        self.assertEqual(task.message.raw, original_message)
        self.assertEqual(task.message.subject, "Original subject")
        self.assertEqual(task.message.sender, "billing@example.test")
        self.assertEqual(first.diagnostics["OPAQUE-X"], ())

    def test_unknown_multisources_and_empty_task_are_preserved_without_accounting_defaults(self):
        self.sources("OPAQUE-X", {"invoice.xml": XML, "dua.txt": "Customs VAT", "hours.txt": "Work hours"},
                     declared=["invoice.xml", "missing.pdf"])
        self.ids.append("EMPTY-NEW")
        self.tasks(self.ids)
        run = self.prepare()
        loaded = self.load(run)
        attachments = loaded["OPAQUE-X"].attachments
        self.assertEqual(len(attachments), 3)
        failures = [source for source in attachments if source.error]
        self.assertEqual(len(failures), 2)
        self.assertTrue(all(source.error == "RESIDUAL_EXTRACTION_REQUIRED" and source.facts is None
                            and source.normalized is None and source.classification is None for source in failures))
        self.assertIn("MISSING_ATTACHMENT:missing.pdf", loaded.diagnostics["OPAQUE-X"])
        self.assertIn("UNLISTED_ATTACHMENT:hours.txt", loaded.diagnostics["OPAQUE-X"])
        empty = loaded["EMPTY-NEW"]
        self.assertEqual((empty.attachments, empty.message.raw, empty.message.source_sha256), ((), {}, ""))
        self.assertEqual(loaded.diagnostics["EMPTY-NEW"], ("MISSING_DOCUMENT_SOURCE", "MISSING_MESSAGE"))

    def test_empty_xml_leaves_are_literal_unknown_values_and_are_not_discarded(self):
        original = XML.replace("<InvoiceNumber>F-OTHER</InvoiceNumber>",
                               "<InvoiceNumber>F-OTHER</InvoiceNumber><InvoiceSeriesCode/>")
        self.sources("OPAQUE-X", {"invoice.xml": original})
        loaded = self.load(self.prepare())
        attachment, = loaded["OPAQUE-X"].attachments
        series, = attachment.facts.fields["raw.series"]
        self.assertEqual((series.value, series.evidence.quote), ("", ""))
        self.assertIsNone(attachment.error)

    def test_fixture_mode_and_contradictory_candidates_remain_explicit(self):
        self.sources("OPAQUE-X", {"invoice.xml": XML, "invoice.txt": "Invoice total 12.34 or 13.34"})
        parsed = DocumentRouter(self.phase).parse("inbox/ap/OPAQUE-X/invoice.txt")
        raw = DocumentFacts(parsed.source_sha256, "fixture-v1", {
            "document_type_hint": [Fact("Invoice", Evidence(parsed.path, "text", quote="Invoice"))],
            "gross": [Fact(value, Evidence(parsed.path, "text", quote=value)) for value in ("12.34", "13.34")]})
        config = RecordingConfig("fixture", "fixture-model", "fixture-v1", "prompt-v1",
                                 "a" * 64, "schema-v1", "b" * 64)
        store = RecordingStore(self.root / "captures")
        store.save("extract", parsed, config, ExtractionCapture(raw, {}, {}, unknowns=({"field": "net"},)),
                   origin="synthetic")
        run = self.prepare(mode="fixture", extractor=RecordedExtractor(store, config, mode="fixture"))
        with patch("socket.socket", side_effect=AssertionError("network disabled")), \
                patch.object(RecordedExtractor, "__init__", side_effect=AssertionError("no capture adapter")):
            loaded = self.load(run)
        self.assertEqual(loaded.source_mode, "fixture")
        invoice = next(source for source in loaded["OPAQUE-X"].attachments if source.path.endswith(".txt"))
        self.assertEqual([fact.value for fact in invoice.normalized.conflicts["gross_cents"]], [1234, 1334])
        self.assertEqual(invoice.unknowns, ({"field": "net"},))
        self.assertEqual(invoice.facts.to_dict(), raw.to_dict())
        manifest = deepcopy(run.manifest)
        manifest["mode"] = "record"
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "capture origin.*manifest mode"):
            self.load(run)
        self.write_manifest(run.manifest)
        def mutate_key(artifact):
            artifact["recording_key"] = "c" * 64
        # Mutate the residual artifact while retaining valid content checksums.
        manifest = deepcopy(run.manifest)
        stage = next(stage for stage in manifest["documents"][0]["attachments"] if stage["path"].endswith(".txt"))
        artifact = json.loads((self.state / stage["artifact"]).read_text())
        mutate_key(artifact)
        key = fingerprint(dict(config=manifest["configuration"], source=artifact))
        stage["artifact"] = "sources/" + key + ".json"
        path = self.state / stage["artifact"]
        atomic_json(path, artifact)
        stage["artifact_sha256"] = digest(path.read_bytes())
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "recording key.*source/configuration"):
            self.load(run)

    def test_artifact_byte_mutation_is_refused(self):
        run = self.prepare()
        stage = run.manifest["documents"][0]["attachments"][0]
        artifact = self.state / stage["artifact"]
        artifact.write_text(artifact.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "artifact SHA-256"):
            self.load(run)

    def test_rehashed_normalized_mutation_is_refused_by_current_conversion(self):
        run = self.prepare()
        def mutate(artifact):
            artifact["normalized"]["fields"]["payable_cents"][0]["value"] = 9999
        self.alter_artifact(run, mutate)
        with self.assertRaisesRegex(ValueError, "current conversion"):
            self.load(run)

    def test_rehashed_parsed_block_mutation_is_refused_against_original(self):
        run = self.prepare()
        def mutate(artifact):
            artifact["parsed"]["blocks"][0]["text"] = "invented source text"
        self.alter_artifact(run, mutate)
        with self.assertRaisesRegex(ValueError, "original blocks"):
            self.load(run)

    def test_original_attachment_message_task_and_clock_mutations_are_refused(self):
        run = self.prepare()
        originals = [self.phase / "inbox/ap/OPAQUE-X/invoice.xml",
                     self.phase / "inbox/ap/OPAQUE-X/message.json",
                     self.phase / "tasks/ap_documents.json", self.phase / "tasks/close.json"]
        for path in originals:
            before = path.read_bytes()
            with self.subTest(path=path):
                path.write_bytes(before + b" ")
                with self.assertRaises(ValueError):
                    self.load(run)
                path.write_bytes(before)
        new_attachment = self.phase / "inbox/ap/OPAQUE-X/new.txt"
        new_attachment.write_text("new original")
        with self.assertRaisesRegex(ValueError, "source inventory|every original attachment"):
            self.load(run)

    def test_metadata_all_fields_and_config_versions_cannot_be_rewritten_with_a_new_fingerprint(self):
        run = self.prepare()
        manifest = deepcopy(run.manifest)
        manifest["documents"][0]["metadata"]["fields"]["body"][0]["value"] = "Different body"
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "all original message fields"):
            self.load(run)
        manifest = deepcopy(run.manifest)
        manifest["configuration"]["normalization"] = "different-normalization"
        self.write_manifest(manifest)
        with self.assertRaisesRegex(ValueError, "configuration versions"):
            self.load(run)

    def test_manifest_fingerprint_and_artifact_source_origin_are_guarded(self):
        run = self.prepare()
        manifest = deepcopy(run.manifest)
        manifest["documents"][0]["doc_id"] = "INVENTED-ID"
        atomic_json(run.manifest_path, manifest)
        with self.assertRaisesRegex(ValueError, "manifest fingerprint"):
            self.load(run)
        atomic_json(run.manifest_path, run.manifest)
        self.alter_artifact(run, lambda artifact: artifact.update(path="inbox/ap/OTHER-7/invoice.xml"))
        with self.assertRaisesRegex(ValueError, "exact original source/path"):
            self.load(run)

    def test_golden_original_and_symlink_artifact_paths_are_refused(self):
        run = self.prepare()
        with self.assertRaisesRegex(ValueError, "original phase and Golden"):
            load_prepared_ap_sources(self.phase, self.phase / "phase-sources.json")
        with self.assertRaisesRegex(ValueError, "original phase and Golden"):
            load_prepared_ap_sources(self.phase, self.root / "golden/phase-sources.json")
        with self.assertRaisesRegex(ValueError, "golden"):
            load_prepared_ap_sources(self.phase / "golden", run.manifest_path)
        stage = run.manifest["documents"][0]["attachments"][0]
        artifact = self.state / stage["artifact"]
        artifact.unlink()
        artifact.symlink_to(self.phase / "inbox/ap/OPAQUE-X/invoice.xml")
        with self.assertRaisesRegex(ValueError, "artifact path escapes"):
            self.load(run)

    def test_concurrent_original_change_prevents_returning_a_mixed_snapshot(self):
        run = self.prepare()
        parse = DocumentRouter.parse
        def mutate(router, relative):
            document = parse(router, relative)
            clock = self.phase / "tasks/close.json"
            clock.write_text(clock.read_text() + " ")
            return document
        with patch.object(DocumentRouter, "parse", mutate):
            with self.assertRaisesRegex(ValueError, "snapshot changed while loading"):
                self.load(run)


if __name__ == "__main__":
    unittest.main()
