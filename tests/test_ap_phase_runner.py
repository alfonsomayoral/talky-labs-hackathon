"""Saved-source, full-inventory composition uses real accounting and export."""
import asyncio
import contextlib
import io
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch

from kalmora.ap_phase_export import write_phase_ap_jsonl
from kalmora.ap_phase_runner import run_ap_phase
from kalmora.ap_sources import prepare_ap_sources
from kalmora.cli import main
from kalmora.documents.contracts import fingerprint
from kalmora.documents.replay import ExtractionCapture, RecordedExtractor, RecordingConfig, RecordingStore
from kalmora.documents.router import DocumentRouter
from kalmora.facts import DocumentFacts, Evidence, Fact
from tests import test_ap_posting_source_bridge as posting_fixtures


class APPhaseRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = posting_fixtures.PostingSourceBridgeTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tmp.cleanup)
        self.phase = self.fixture.phase
        self.root = self.phase.parent
        self.fixture.vendor.update(alternative_payee=None, garnishments=[], currency="EUR")
        self.fixture.write("vendors", [self.fixture.vendor])
        self.fixture.write("contractor_certificates", [])
        self.config = RecordingConfig("fixture", "fixture-model", "phase-fixture-v1", "prompt-v1",
            "a" * 64, "schema-v1", "b" * 64)
        self.store = RecordingStore(self.root / "captures")
        self.ids = []
        fields = {**self.fixture.fields, "invoice_number": "INV-100"}
        self.add_source("POST-OPAQUE", fields, "2044-02-10T09:00:00Z")
        self.add_source("DUP-OPAQUE", fields, "2044-02-10T10:00:00Z")
        self.add_source("REJECT-OPAQUE", {**fields, "invoice_number": "INV-200",
            "recipient_tax_id": "BUYER-OTHER"}, "2044-02-11T09:00:00Z")
        held = {**fields, "invoice_number": "INV-300", "net": "300.00", "tax": "63.00",
            "gross": "363.00", "payable": "363.00", "line.1.amount": "300.00", "line.1.quantity": "3"}
        del held["line.1.net"]
        self.add_source("HOLD-OPAQUE", held, "2044-02-12T09:00:00Z")
        self.add_source("NOTICE-OPAQUE", {"document_type_hint": "Proforma"}, "2044-02-13T09:00:00Z")
        self.prepared = await self.prepare()

    def add_source(self, doc_id, fields, received):
        self.ids.append(doc_id)
        folder = self.phase / "inbox/ap" / doc_id
        folder.mkdir(parents=True)
        (folder / "message.json").write_text(json.dumps(dict(doc_id=doc_id, received_at=received,
            channel="EMAIL", attachments=["source.txt"])))
        (folder / "source.txt").write_text("\n".join(f"{name}: {value}" for name, value in fields.items()))
        relative = f"inbox/ap/{doc_id}/source.txt"
        parsed = DocumentRouter(self.phase).parse(relative)
        block = parsed.blocks[0]
        facts = DocumentFacts(parsed.source_sha256, self.config.extractor_version,
            {name: [Fact(value, Evidence(relative, block.source_field or block.id, block.page, str(value)))]
             for name, value in fields.items()})
        self.store.save("extract", parsed, self.config, ExtractionCapture(facts, {}, {}), origin="synthetic")

    async def prepare(self):
        (self.phase / "tasks/ap_documents.json").write_text(json.dumps(self.ids))
        return await prepare_ap_sources(self.phase, self.root / "saved", mode="fixture",
            extractor=RecordedExtractor(self.store, self.config, mode="fixture"))

    async def run_phase(self, **changes):
        options = dict(receipt_as_of=self.fixture.cutoff, posting_date=self.fixture.posted)
        options.update(changes)
        return await run_ap_phase(self.phase, self.prepared.manifest_path, **options)

    async def test_real_policies_cover_all_decisions_and_publish_only_one_journal_and_receipt_use(self):
        result = await self.run_phase()
        self.assertTrue(result.complete, [(item["task_key"], item["diagnostics"]) for item in result.report["tasks"]])
        by_id = {row["doc_id"]: row for row in result.rows}
        self.assertEqual({key: row["decision"] for key, row in by_id.items()}, {
            "POST-OPAQUE": "POST", "DUP-OPAQUE": "DUPLICATE", "REJECT-OPAQUE": "REJECT",
            "HOLD-OPAQUE": "HOLD", "NOTICE-OPAQUE": "NOT_INVOICE"})
        self.assertEqual(by_id["DUP-OPAQUE"]["duplicate_of"], "POST-OPAQUE")
        self.assertEqual(by_id["REJECT-OPAQUE"]["reasons"], ["WRONG_ADDRESSEE"])
        self.assertEqual(by_id["HOLD-OPAQUE"]["reasons"], ["QTY_NOT_RECEIVED"])
        self.assertTrue(all("journal_entry" not in row for row in result.rows if row["decision"] != "POST"))
        self.assertEqual([row["doc_id"] for row in result.state.rows], ["POST-OPAQUE"])
        self.assertEqual(sum(use.quantity_milli for use in result.state.consumption.usages), 1000)
        lines = by_id["POST-OPAQUE"]["journal_entry"]["lines"]
        self.assertEqual(sum(line["debit"] for line in lines), sum(line["credit"] for line in lines))
        self.assertTrue(all(line.get("partner") == "SUPPLIER-ZETA" for line in lines if line["account"] == "41000000"))
        receipt = write_phase_ap_jsonl(self.root / "delivery/ap.jsonl", result.rows,
            phase_path=self.phase, tax_catalog=result.tax_catalog)
        self.assertEqual(receipt.row_count, len(self.ids))

    async def test_saved_source_replay_has_no_network_golden_interpretation_or_double_consumption(self):
        def denied(*args, **kwargs):
            raise AssertionError("provider/interpretation disabled")
        original_open = Path.open
        def guarded_open(path, *args, **kwargs):
            if any(part.lower() == "golden" for part in (*path.parts, *path.resolve().parts)):
                raise AssertionError("Golden unavailable")
            return original_open(path, *args, **kwargs)
        with patch.object(socket.socket, "connect", denied), patch.object(socket, "create_connection", denied), \
                patch.object(RecordedExtractor, "__init__", denied), patch.object(Path, "open", guarded_open):
            first = await self.run_phase()
            second = await self.run_phase()
        self.assertEqual(first.rows, second.rows)
        self.assertEqual(first.report["stable_run_sha256"], second.report["stable_run_sha256"])
        self.assertEqual(first.state.consumption, second.state.consumption)
        self.assertEqual(first.report["execution"]["new_provider_calls"], 0)
        stable = {k: v for k, v in first.report.items() if k not in {"execution", "stable_run_sha256"}}
        self.assertEqual(first.report["stable_run_sha256"], fingerprint(stable))

    async def test_unknown_new_attachment_prevents_negative_duplicate_claim_and_never_fakes_coverage(self):
        folder = self.phase / "inbox/ap/UNRESOLVED-OPAQUE"
        folder.mkdir()
        (folder / "message.json").write_text(json.dumps(dict(doc_id="UNRESOLVED-OPAQUE",
            received_at="2044-02-10T08:00:00Z", attachments=["unknown.txt"])))
        (folder / "unknown.txt").write_text("uninterpreted original")
        self.ids.append("UNRESOLVED-OPAQUE")
        self.prepared = await self.prepare()
        result = await self.run_phase()
        self.assertFalse(result.complete)
        unknown = next(item for item in result.report["tasks"] if item["task_key"] == "UNRESOLVED-OPAQUE")
        self.assertEqual(unknown["status"], "UNKNOWN")
        self.assertIsNone(unknown["row"])
        self.assertEqual(result.report["summary"]["task_count"], len(self.ids))
        self.assertEqual(result.report["summary"]["decided_count"]+result.report["summary"]["unresolved_count"], len(self.ids))
        self.assertFalse(result.report["run"]["exportsAP"])

    async def test_missing_posting_date_does_not_mask_earlier_hold_reject_or_duplicate(self):
        result = await self.run_phase(posting_date=None)
        self.assertFalse(result.complete)
        decisions = {item["task_key"]: item["decision"] for item in result.report["tasks"]}
        self.assertIsNone(decisions["POST-OPAQUE"])
        self.assertEqual(decisions["DUP-OPAQUE"], "DUPLICATE")
        self.assertEqual(decisions["REJECT-OPAQUE"], "REJECT")
        self.assertEqual(decisions["HOLD-OPAQUE"], "HOLD")
        self.assertEqual(result.state.rows, ())
        self.assertEqual(result.state.consumption.usages, ())

    async def test_missing_currency_is_a_task_unknown_without_calling_notice_with_fabricated_scope(self):
        fields = {**self.fixture.fields, "invoice_number": "INV-UNKNOWN-CURRENCY"}
        del fields["currency"]
        self.add_source("MISSING-CURRENCY", fields, "2044-02-14T09:00:00Z")
        self.prepared = await self.prepare()
        result = await self.run_phase()
        task = next(item for item in result.report["tasks"] if item["task_key"] == "MISSING-CURRENCY")
        self.assertEqual(task["status"], "UNKNOWN")
        self.assertIsNone(task["row"])
        self.assertEqual(result.report["summary"]["task_count"], len(self.ids))
        self.assertFalse(result.complete)

    async def test_standalone_signed_bank_notice_resolves_exact_tax_ids_without_internal_codes(self):
        self.ids = []
        self.add_source("STANDALONE-BANK", dict(document_type_hint="BANK_DETAILS_CHANGE",
            supplier_tax_id="TAX-ZETA", recipient_tax_id="BUYER-ZETA", currency="EUR",
            new_iban="ES NEW", signed=True, bank_certificate_present=True), "2044-02-15T09:00:00Z")
        self.prepared = await self.prepare()
        first = await self.run_phase(posting_date=None)
        second = await self.run_phase(posting_date=None)
        self.assertTrue(first.complete, first.report["tasks"][0]["diagnostics"])
        self.assertEqual((first.rows[0]["decision"], first.rows[0]["action"]),
                         ("NOT_INVOICE", "UPDATE_BANK_DETAILS"))
        self.assertEqual(first.rows, second.rows)
        self.assertEqual(first.state.rows, ())
        self.assertEqual(first.state.consumption.usages, ())

    async def test_manifest_redirect_after_authentication_never_opens_golden_bytes(self):
        from kalmora.ap_sources import load_prepared_ap_sources
        manifest = self.prepared.manifest_path
        original = manifest.read_bytes()
        golden = self.root / "golden/saved.json"
        golden.parent.mkdir()
        golden.write_bytes(original)
        def redirected(*args, **kwargs):
            prepared = load_prepared_ap_sources(*args, **kwargs)
            manifest.unlink()
            manifest.symlink_to(golden)
            return prepared
        original_open = Path.open
        def guarded(path, *args, **kwargs):
            if "golden" in path.parts or "golden" in path.resolve().parts:
                raise AssertionError("forbidden Golden read")
            return original_open(path, *args, **kwargs)
        with patch("kalmora.ap_phase_runner.load_prepared_ap_sources", side_effect=redirected), \
                patch.object(Path, "open", guarded):
            with self.assertRaisesRegex(ValueError, "redirected"):
                await self.run_phase()

    async def test_changed_coding_master_after_policy_evaluation_rejects_whole_run(self):
        from kalmora.ap_pipeline import evaluate_ap_invoice
        changed = False
        def mutate(*args, **kwargs):
            nonlocal changed
            result = evaluate_ap_invoice(*args, **kwargs)
            if not changed:
                changed = True
                self.fixture.write("cost_centers", [])
            return result
        with patch("kalmora.ap_phase_runner.evaluate_ap_invoice", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "source changed"):
                await self.run_phase(posting_date=None)

    async def test_cli_exports_complete_run_and_incomplete_run_preserves_old_output(self):
        output, report = self.root / "ap.jsonl", self.root / "audit.json"
        cutoff, posted = self.root / "cutoff.json", self.root / "posted.json"
        def fact_json(fact):
            return dict(value=fact.value, evidence=dict(document=fact.evidence.document, field=fact.evidence.field))
        cutoff.write_text(json.dumps(fact_json(self.fixture.cutoff)))
        posted.write_text(json.dumps(fact_json(self.fixture.posted)))
        arguments = ["--run-dir", str(self.root / "reports"), "solve-ap", str(self.phase),
            "--sources", str(self.prepared.manifest_path), "--output", str(output), "--report", str(report),
            "--receipt-cutoff-fact", str(cutoff)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = await asyncio.to_thread(main, [*arguments, "--posting-date-fact", str(posted)])
        self.assertEqual(code, 0, stderr.getvalue())
        self.assertTrue(json.loads(stdout.getvalue())["exported"])
        original = output.read_bytes()
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = await asyncio.to_thread(main, [*arguments, "--overwrite"])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(stdout.getvalue())["exported"])
        self.assertEqual(output.read_bytes(), original)
        self.assertFalse(json.loads(report.read_text())["publication"]["exported"])

    async def test_cli_protected_destinations_rejected_before_creating_run_reports(self):
        reports = self.root / "never-reports"
        for output in (self.phase / "ap.jsonl", self.root / "golden/ap.jsonl", self.prepared.manifest_path):
            with contextlib.redirect_stderr(io.StringIO()):
                code = await asyncio.to_thread(main, ["--run-dir", str(reports), "solve-ap", str(self.phase),
                    "--sources", str(self.prepared.manifest_path), "--output", str(output),
                    "--report", str(self.root / "report.json")])
            self.assertEqual(code, 1)
            self.assertFalse(reports.exists())
