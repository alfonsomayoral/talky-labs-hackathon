"""Acceptance boundaries through actual factories; fixtures are never phase results."""
import asyncio
from contextlib import redirect_stdout
from copy import deepcopy
from dataclasses import replace
import importlib.util
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from kalmora.ap_acceptance import audit_ap_delivery, compare_ap_acceptance, replay_ap_transactions
from kalmora.ap_output import build_ap_row, validate_ap_row
from kalmora.ap_phase_export import write_phase_ap_jsonl
from kalmora.ap_sources import prepare_ap_sources
from kalmora.ap_transaction import APTransactionState
from kalmora.ap_journal import AdvanceApplication, InvoiceLineOrder
from kalmora.money import RateTable
import test_ap_transaction as transaction_fixtures
from kalmora.documents.contracts import fingerprint
from kalmora.documents.replay import RecordedExtractor, RecordingConfig, RecordingStore


XML = '''<Facturae><FileHeader><SchemaVersion>3.2.2</SchemaVersion></FileHeader>
<Invoices><Invoice><InvoiceHeader><InvoiceClass>OO</InvoiceClass><InvoiceNumber>N-NEW</InvoiceNumber></InvoiceHeader>
<InvoiceIssueData><IssueDate>2026-07-01</IssueDate><InvoiceCurrencyCode>EUR</InvoiceCurrencyCode></InvoiceIssueData>
<InvoiceTotals><TotalGrossAmount>100.00</TotalGrossAmount><TotalTaxOutputs>0</TotalTaxOutputs>
<InvoiceTotal>100.00</InvoiceTotal></InvoiceTotals></Invoice></Invoices></Facturae>'''


class APAcceptanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.phase, self.bundle = self.root / "phase", self.root / "bundle"
        self.policy = self.root / "POLITICAS_CONTABLES.md"
        self.policy.write_text("synthetic policy §1–2")
        (self.root / "FORMATO_ENTREGA.md").write_text("synthetic AP format")
        self.rules = self.root / "rules"
        self.rules.mkdir()
        (self.rules / "installed.py").write_text("version = 1\n")
        self.engine = transaction_fixtures.APTransactionIntegrationTests()
        self.engine.setUp()
        self.engine.context.update(min_date="2026-07-01", max_date="2026-07-31")
        self.request = self.engine.request(date="2026-07-01")
        self.options = dict(tax_catalog=self.engine.tax_catalog,
                            withholding_catalog=self.engine.withholding_catalog, context=self.engine.context)
        self.proof = replay_ap_transactions([self.request], self.engine.baseline, **self.options)
        self.row = json.loads(self.proof.rows_json)
        self.write("tasks/close.json", {"month": "2026-07"})
        self.write("tasks/ap_documents.json", ["I1"])
        self.write("erp/companies.json", [{"code": "1100", "currency": "EUR"}])
        self.write("erp/vendors.jsonl", [{"id": "SUP-OTHER", "companies": ["1100"]}], lines=True)
        self.write("erp/customers.jsonl", [], lines=True)
        self.write("erp/cost_centers.jsonl", [{"id": "CC-OTHER", "company": "1100"}], lines=True)
        self.write("erp/projects.jsonl", [], lines=True)
        self.write("erp/chart_of_accounts.jsonl", [{"account": account} for account in self.engine.context["accounts"]], lines=True)
        self.write("erp/purchase_orders.jsonl", [{"id": "PO-OTHER", "company": "1100", "vendor": "SUP-OTHER",
                   "currency": "EUR", "items": [{"item": 10}]}], lines=True)
        self.write("erp/tax_codes.json", {"tax_codes": {"SEX": {"country": "ES", "kind": "exempt", "rate": 0}}})
        self.write("inbox/ap/I1/message.json", {"doc_id": "I1", "attachments": ["invoice.xml"]})
        (self.phase / "inbox/ap/I1/invoice.xml").write_text(XML)
        self.source = asyncio.run(prepare_ap_sources(self.phase, self.root / "sources"))
        self.export([self.row])

    def write(self, relative, value, *, lines=False):
        path = self.phase / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(row) + "\n" for row in value) if lines else json.dumps(value))

    def export(self, rows):
        return write_phase_ap_jsonl(self.bundle / "deliverables/ap.jsonl", rows, phase_path=self.phase,
                                    tax_catalog=self.engine.tax_catalog, context=self.engine.context, overwrite=True)

    def audit(self, **options):
        return audit_ap_delivery(**{**dict(phase_path=self.phase, bundle_path=self.bundle,
                policy_path=self.policy, source_manifest_path=self.source.manifest_path,
                replay=self.proof, rules_root=self.rules), **options})

    def test_real_factory_replay_matches_export_without_new_consumption_or_events(self):
        original = deepcopy(self.engine.baseline)
        result = self.audit()
        self.assertEqual(result["status"], "READY_FOR_EVALUATION")
        self.assertEqual(result["coverage"], dict(expected=1, rows=1, missing=[], extra=[], duplicate=[], exact=True))
        self.assertEqual(result["journal_totals"]["1100/EUR"], {"debit": 10000, "credit": 10000})
        self.assertEqual(result["replay"]["duplicate_attempts_rejected"], 1)
        self.assertEqual(result["replay"]["provider_calls"], 0)
        self.assertEqual(self.engine.baseline, original)
        repeated = self.audit()
        self.assertEqual(result, repeated)
        self.assertTrue(compare_ap_acceptance(result, repeated)["compatible"])

    def test_foreign_replay_keeps_document_cents_distinct_from_local_balance(self):
        request = self.engine.request(date="2026-07-01", currency="USD")
        rates = RateTable([dict(currency="USD", date="2026-07-01", rate="2"),
                           dict(currency="USD", date="2026-07-11", rate="4")])
        proof = replay_ap_transactions([request], APTransactionState(), rates=rates, **self.options)
        row = json.loads(proof.rows_json)
        self.export([row])
        self.write("erp/purchase_orders.jsonl", [{"id": "PO-OTHER", "company": "1100", "vendor": "SUP-OTHER",
                   "currency": "USD", "items": [{"item": 10}]}], lines=True)
        result = self.audit(replay=proof)
        self.assertEqual(result["status"], "READY_FOR_EVALUATION")
        self.assertEqual(result["journal_totals"]["1100/EUR"], dict(debit=5000, credit=5000))
        dimensions, = result["accounting_dimensions"]
        self.assertEqual((dimensions["document_currency"], dimensions["local_currency"]), ("USD", "EUR"))
        self.assertEqual(dimensions["coding"][0]["amount"], 10000)

    def test_advance_creation_and_application_replay_do_not_double_consume(self):
        advance = self.engine.advance_request()
        advance = replace(advance, scope=replace(advance.scope, invoice_date="2026-07-01"),
            posting=replace(advance.posting, posting_date="2026-07-02",
                            header=replace(advance.posting.header, invoice_date="2026-07-01")))
        invoice = self.engine.request("APPLIED", date="2026-07-10")
        invoice = replace(invoice, posting=replace(invoice.posting,
            header=replace(invoice.posting.header, payable=6000),
            advances=(AdvanceApplication("DEPOSIT-OTHER", 4000, "MONETARY", "EXPLICIT-CLASSIFICATION", line_id="L-OTHER"),),
            invoice_orders=("PO-OTHER",),
            order_bindings=(InvoiceLineOrder("L-OTHER", "PO-OTHER", 10000, "EXPLICIT-BINDING"),)))
        baseline = APTransactionState()
        proof = replay_ap_transactions([advance, invoice], baseline, **self.options)
        self.assertEqual(proof.duplicate_attempts_rejected, 2)
        rows = [json.loads(line) for line in proof.rows_json.splitlines()]
        application = next(row for row in rows if row["doc_id"] == "APPLIED")
        self.assertEqual(application["payable"], 6000)
        credit, = [line for line in application["journal_entry"]["lines"] if line["account"] == "40700000"]
        self.assertEqual(credit["credit"], 4000)
        self.assertEqual((baseline.advances.balances, baseline.advances.events, baseline.consumption.usages), ((), (), ()))

    def test_missing_replay_or_saved_facts_never_claims_monthly_acceptance(self):
        result = self.audit(replay=None)
        self.assertIn("TRANSACTION_REPLAY_ABSENT", result["blockers"])
        self.assertEqual(result["status"], "BLOCKED")

    def test_independent_phase_freeze_requires_same_model_prompt_configuration(self):
        first = self.audit()
        independent = deepcopy(first)
        independent.update(month="2026-09", inputs_sha256="independent-inputs")
        independent["facts"].update(sha256="independent-facts", configuration_sha256="different-model-or-prompt")
        independent["report_sha256"] = fingerprint({key: value for key, value in independent.items() if key != "report_sha256"})
        comparison = compare_ap_acceptance(first, independent, independent_phase=True)
        self.assertFalse(comparison["compatible"])
        self.assertEqual(comparison["differences"], ["facts.configuration_sha256"])
        independent["facts"]["configuration_sha256"] = first["facts"]["configuration_sha256"]
        independent["report_sha256"] = fingerprint({key: value for key, value in independent.items() if key != "report_sha256"})
        self.assertTrue(compare_ap_acceptance(first, independent, independent_phase=True)["compatible"])

    def test_invalid_rows_with_replay_and_traces_still_produce_output_errors(self):
        path = self.bundle / "deliverables/ap.jsonl"
        trace = self.bundle / "trace/events.jsonl"
        trace.parent.mkdir()
        trace.write_text(json.dumps(dict(event_id="E1", item="ap:I1", seq=1, kind="CHECK")))
        for row in ({}, {"decision": "POST"}, {"doc_id": "I1"}, {"doc_id": "I1", "decision": []}):
            path.write_text(json.dumps(row))
            result = self.audit()
            self.assertIn("AP_OUTPUT_INVALID", result["blockers"])
            self.assertTrue(result["output_errors"])
            self.assertEqual(result["status"], "BLOCKED")
        result = self.audit(source_manifest_path=None)
        self.assertIn("SAVED_FACTS_ABSENT", result["blockers"])
        self.assertEqual(result["status"], "BLOCKED")

    def test_source_only_and_partial_output_preserve_exact_task_coverage(self):
        path = self.bundle / "deliverables/ap.jsonl"
        path.unlink()
        result = self.audit()
        self.assertEqual((result["scope"], result["output_sha256"]), ("SOURCE_ONLY", None))
        self.assertEqual(result["coverage"]["missing"], ["I1"])
        self.write("tasks/ap_documents.json", ["I1", "MISSING"])
        path.write_text(json.dumps(self.row) + "\n" + json.dumps(self.row) + "\n" + json.dumps({**self.row, "doc_id": "EXTRA"}))
        before = path.read_bytes()
        result = self.audit(source_manifest_path=None, replay=None)
        self.assertEqual(result["coverage"]["missing"], ["MISSING"])
        self.assertEqual(result["coverage"]["extra"], ["EXTRA"])
        self.assertEqual(result["coverage"]["duplicate"], ["I1"])
        self.assertEqual(result["scope"], "PARTIAL_DELIVERY")
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_cents_dimension_po_currency_or_unbalanced_output_is_not_repaired(self):
        for mutate in (
            lambda row: row.update(net=True),
            lambda row: row["lines"][0].update(cost_center="NO-MASTER"),
            lambda row: row["lines"][0].update(po="OTHER-PO"),
            lambda row: row["journal_entry"]["lines"][0].update(debit=1),
            lambda row: row.update(currency="USD"),
        ):
            row = deepcopy(self.row); mutate(row)
            path = self.bundle / "deliverables/ap.jsonl"
            path.write_text(json.dumps(row))
            before = path.read_bytes()
            result = self.audit()
            self.assertIn("AP_OUTPUT_INVALID", result["blockers"])
            self.assertEqual(path.read_bytes(), before)

    def test_nonposting_never_changes_transaction_state_or_carries_a_journal(self):
        request = replace(self.request, scope=replace(self.request.scope, decision="HOLD"), posting=None)
        proof = replay_ap_transactions([request], self.engine.baseline, **self.options)
        self.assertEqual(proof.initial_state_sha256, proof.final_state_sha256)
        row = build_ap_row(doc_id="I1", document_type="INVOICE", decision="HOLD", reasons=["QTY_NOT_RECEIVED"])
        self.export([row])
        self.assertEqual(self.audit(replay=proof)["status"], "READY_FOR_EVALUATION")
        row["journal_entry"] = self.row["journal_entry"]
        (self.bundle / "deliverables/ap.jsonl").write_text(json.dumps(row))
        self.assertIn("AP_OUTPUT_INVALID", self.audit(replay=proof)["blockers"])

    def test_nonposting_replay_requires_same_decision_and_document_type(self):
        request = replace(self.request, scope=replace(self.request.scope, decision="HOLD"), posting=None)
        proof = replay_ap_transactions([request], self.engine.baseline, **self.options)
        self.assertEqual(proof.nonposting_projection, (("I1", "INVOICE", "HOLD"),))
        for kind, decision, reason in (("INVOICE", "REJECT", "ARITHMETIC_ERROR"),
                                       ("CREDIT_NOTE", "HOLD", "QTY_NOT_RECEIVED")):
            row = build_ap_row(doc_id="I1", document_type=kind, decision=decision, reasons=[reason])
            self.export([row])
            self.assertIn("TRANSACTION_REPLAY_OUTPUT_MISMATCH", self.audit(replay=proof)["blockers"])

    def test_saved_sources_modified_originals_rules_and_cross_phase_reuse_are_visible(self):
        before = self.audit()
        (self.phase / "inbox/ap/I1/invoice.xml").write_text(XML.replace("N-NEW", "CHANGED"))
        after = self.audit()
        self.assertEqual(after["facts"]["status"], "INCOMPATIBLE")
        self.assertFalse(compare_ap_acceptance(before, after)["compatible"])
        (self.rules / "installed.py").write_text("version = 2\n")
        updated = self.audit()
        self.assertIn("rules_sha256", compare_ap_acceptance(before, updated, independent_phase=True)["differences"])
        with self.assertRaises(ValueError):
            compare_ap_acceptance({**before, "output_sha256": "pretend"}, after)

    def test_content_addressed_but_forged_normalization_and_classification_are_blocked(self):
        # Recompute all public integrity hashes: only source-derived semantics
        # can distinguish this internally consistent forgery from valid facts.
        original = json.loads(self.source.manifest_path.read_bytes())
        stage = original["documents"][0]["attachments"][0]
        artifact = json.loads((self.source.manifest_path.parent / stage["artifact"]).read_bytes())
        for field, value in (("normalized", {**artifact["normalized"], "fields": {}}),
                             ("classification", {**artifact["classification"], "document_type": "CREDIT_NOTE"})):
            manifest = deepcopy(original)
            forged = {**deepcopy(artifact), field: value}
            key = fingerprint(dict(config=manifest["configuration"], source=forged))
            forged_path = self.source.manifest_path.parent / "sources" / (key + ".json")
            encoded = json.dumps(forged).encode()
            forged_path.write_bytes(encoded)
            current_stage = manifest["documents"][0]["attachments"][0]
            current_stage.update(artifact="sources/" + key + ".json", artifact_sha256=hashlib.sha256(encoded).hexdigest())
            if field == "classification":
                current_stage["classification"] = "CREDIT_NOTE"
            manifest["stable_source_sha256"] = fingerprint({name: manifest[name] for name in
                ("month", "task_sha256", "close_sha256", "configuration", "documents")})
            self.source.manifest_path.write_text(json.dumps(manifest))
            result = self.audit()
            self.assertEqual(result["facts"]["status"], "INCOMPATIBLE")
            self.assertTrue(any(error.startswith("PREPARED_SOURCE_INVALID:") for error in result["blockers"]))
            self.assertEqual(result["status"], "BLOCKED")

    def replace_prepared_artifact(self, artifact):
        """Publish altered saved bytes with consistent public integrity hashes."""
        manifest = json.loads(self.source.manifest_path.read_bytes())
        key = fingerprint(dict(config=manifest["configuration"], source=artifact))
        relative = "sources/" + key + ".json"
        payload = json.dumps(artifact).encode()
        (self.source.manifest_path.parent / relative).write_bytes(payload)
        manifest["documents"][0]["attachments"][0].update(
            artifact=relative, artifact_sha256=hashlib.sha256(payload).hexdigest())
        manifest["stable_source_sha256"] = fingerprint({name: manifest[name] for name in
            ("month", "task_sha256", "close_sha256", "configuration", "documents")})
        self.source.manifest_path.write_text(json.dumps(manifest))
        return relative, payload

    def test_saved_field_unknowns_block_even_with_valid_facts_classification_and_replay(self):
        manifest = json.loads(self.source.manifest_path.read_bytes())
        path = manifest["documents"][0]["attachments"][0]["artifact"]
        original = json.loads((self.source.manifest_path.parent / path).read_bytes())
        for field, status in (("invoice.net", "CONTRADICTORY"), ("line.1.quantity", "AMBIGUOUS"),
                              ("recipient_tax_id", "MISSING")):
            with self.subTest(status=status):
                unknown = dict(field=field, status=status, reason="unreadable source")
                artifact = {**deepcopy(original), "unknowns": [unknown]}
                relative, payload = self.replace_prepared_artifact(artifact)
                result = self.audit()
                facts = result["facts"]
                self.assertEqual(facts["status"], "COMPATIBLE")
                self.assertEqual((facts["accepted_attachments"], facts["unknown_attachments"],
                                  facts["unclassified_attachments"], facts["unresolved_source_fields"]), (1, 0, 0, 1))
                self.assertEqual(facts["source_unknowns"], [dict(doc_id="I1", path="inbox/ap/I1/invoice.xml",
                                 artifact=relative, index=1, valid=True, **unknown)])
                self.assertIn("SOURCE_UNDERSTANDING_INCOMPLETE", result["blockers"])
                self.assertEqual(result["status"], "BLOCKED")
                # Audit neither clears a missing field nor rewrites source facts.
                self.assertEqual((self.source.manifest_path.parent / relative).read_bytes(), payload)
                self.assertEqual(json.loads(payload)["raw"], original["raw"])

    def test_invalid_field_unknown_schema_is_preserved_as_invalid_not_a_valid_state(self):
        manifest = json.loads(self.source.manifest_path.read_bytes())
        path = manifest["documents"][0]["attachments"][0]["artifact"]
        original = json.loads((self.source.manifest_path.parent / path).read_bytes())
        valid = dict(field="invoice.net", status="AMBIGUOUS", reason="unreadable source")
        invalid = [None, "MISSING", {**valid, "status": "RESOLVED"}, {**valid, "status": []},
                   {**valid, "status": True}, {**valid, "field": " "}, {**valid, "reason": None},
                   {**valid, "reason": " "}, {**valid, "extra": "ignored?"}, {"field": "net", "status": "MISSING"}]
        for unknown in invalid:
            with self.subTest(unknown=unknown):
                relative, _ = self.replace_prepared_artifact({**deepcopy(original), "unknowns": [unknown]})
                result = self.audit()
                self.assertEqual(result["facts"]["status"], "INCOMPATIBLE")
                self.assertEqual(result["facts"]["source_unknowns"], [dict(doc_id="I1", path="inbox/ap/I1/invoice.xml",
                                 artifact=relative, index=1, valid=False, raw=unknown)])
                self.assertEqual(result["facts"]["unresolved_source_fields"], 0)
                self.assertTrue(any(error.startswith("SOURCE_UNKNOWN_SCHEMA_INVALID:") for error in result["blockers"]))
                self.assertEqual(result["status"], "BLOCKED")

    def test_valid_fixture_preparation_is_not_a_real_source_recording(self):
        config = RecordingConfig("fixture", "fixture", "fixture", "fixture", "1" * 64, "fixture", "2" * 64)
        extractor = RecordedExtractor(RecordingStore(self.root / "fixture-captures"), config, mode="fixture")
        source = asyncio.run(prepare_ap_sources(self.phase, self.root / "fixture-sources", mode="fixture", extractor=extractor))
        result = self.audit(source_manifest_path=source.manifest_path)
        self.assertEqual(result["facts"]["status"], "COMPATIBLE")
        self.assertEqual(result["facts"]["source_mode"], "fixture")
        self.assertIn("FIXTURE_SOURCE_NOT_REAL_RECORDING", result["blockers"])
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(extractor.capture_calls, 0)

    def test_mismatched_replay_and_duplicate_trace_events_block_acceptance(self):
        wrong = replace(self.proof, rows_json=b"[]")
        # A typed proof containing rows from another run cannot attest this output.
        wrong = replace(wrong, rows_json=json.dumps({**self.row, "invoice_number": "OTHER"}).encode())
        self.assertIn("TRANSACTION_REPLAY_OUTPUT_MISMATCH", self.audit(replay=wrong)["blockers"])
        trace = self.bundle / "trace/events.jsonl"
        trace.parent.mkdir()
        event = dict(event_id="E1", item="ap:I1", seq=1, kind="POST")
        trace.write_text(json.dumps(event) + "\n" + json.dumps({**event, "event_id": "E2", "seq": 2}))
        self.assertIn("TRACE_POSTING_DUPLICATE", self.audit()["blockers"])
        trace.write_text(json.dumps(event) + "\n" + json.dumps(event))
        self.assertIn("TRACE_EVENT_DUPLICATE", self.audit()["blockers"])

    def test_snapshot_change_during_validation_fails_instead_of_mixed_acceptance(self):
        def interleave(*args, **kwargs):
            self.write("erp/vendors.jsonl", [{"id": "SUP-OTHER", "companies": ["1200"]}], lines=True)
            return validate_ap_row(*args, **kwargs)
        with patch("kalmora.ap_acceptance.validate_ap_row", side_effect=interleave):
            with self.assertRaisesRegex(ValueError, "changed during audit"):
                self.audit()

    def test_duplicate_json_members_unknown_facts_and_sandbox_boundaries(self):
        (self.bundle / "deliverables/ap.jsonl").write_bytes(b'{"doc_id":"I1","doc_id":"OTHER"}')
        result = self.audit(replay=None)
        self.assertIn("AP_OUTPUT_INVALID", result["blockers"])
        for options in (dict(bundle_path=self.phase / "output"), dict(policy_path=self.root / "golden/policy.md"),
                        dict(source_manifest_path=self.phase / "facts.json")):
            with self.assertRaises(ValueError):
                self.audit(**options)
        (self.phase / "inbox/ap/I1/invoice.xml").unlink()
        (self.phase / "inbox/ap/I1/unparsed.txt").write_text("unsupported attachment")
        self.source = asyncio.run(prepare_ap_sources(self.phase, self.root / "unknown-sources"))
        self.assertIn("SOURCE_UNDERSTANDING_INCOMPLETE", self.audit(replay=None)["blockers"])

    def test_cli_writes_blocked_evidence_and_preserves_existing_report(self):
        script = Path(__file__).resolve().parents[1] / "tools/validate_ap_delivery.py"
        spec = importlib.util.spec_from_file_location("delivery_tool", script)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        destination = self.root / "acceptance.json"
        args = ["--phase", str(self.phase), "--bundle", str(self.bundle), "--policy", str(self.policy),
                "--sources", str(self.source.manifest_path), "--report", str(destination)]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(args), 1)
        original = destination.read_bytes()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(module.main(args), 2)
        self.assertEqual(destination.read_bytes(), original)
        self.assertIn("TRANSACTION_REPLAY_ABSENT", json.loads(original)["blockers"])


class APAcceptanceOriginalSourcesTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("KALMORA_AP_PHASE") and os.environ.get("KALMORA_AP_SOURCES"),
                         "original phase/source manifest not configured")
    def test_original_source_run_is_bound_without_fabricating_a_monthly_delivery(self):
        phase = Path(os.environ["KALMORA_AP_PHASE"])
        sources = Path(os.environ["KALMORA_AP_SOURCES"])
        with tempfile.TemporaryDirectory() as directory:
            report = audit_ap_delivery(phase_path=phase, bundle_path=Path(directory) / "missing-run",
                                      policy_path=phase.parent / "POLITICAS_CONTABLES.md", source_manifest_path=sources)
        self.assertEqual(report["scope"], "SOURCE_ONLY")
        self.assertEqual(report["facts"]["status"], "COMPATIBLE")
        self.assertEqual(report["coverage"]["rows"], 0)
        self.assertEqual(len(report["coverage"]["missing"]), report["coverage"]["expected"])
        self.assertIn("AP_DELIVERY_ABSENT", report["blockers"])
        self.assertIn("TRANSACTION_REPLAY_ABSENT", report["blockers"])
        self.assertIsNone(report["evaluation"]["score"])


if __name__ == "__main__":
    unittest.main()
