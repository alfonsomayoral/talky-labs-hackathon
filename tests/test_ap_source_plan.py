"""Whole task-inventory audits replay without interpretation or accounting output."""
from copy import deepcopy
import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalmora.ap_invoice_context import resolve_ap_invoice_context
from kalmora.ap_order_bridge import APOrderBridge
from kalmora.ap_source_plan import plan_ap_sources
from kalmora.ap_sources import prepare_ap_sources
from kalmora.documents.contracts import digest, fingerprint
from kalmora.documents.replay import ExtractionCapture, RecordedExtractor, RecordingConfig, RecordingStore
from kalmora.documents.router import DocumentRouter
from kalmora.facts import DocumentFacts, Evidence, Fact


XML = '''<Facturae><FileHeader><SchemaVersion>3.2.2</SchemaVersion></FileHeader><Parties><SellerParty><TaxIdentification><TaxIdentificationNumber>SUPPLIERTAX</TaxIdentificationNumber></TaxIdentification></SellerParty>
<BuyerParty><TaxIdentification><TaxIdentificationNumber>BUYERTAX</TaxIdentificationNumber></TaxIdentification></BuyerParty></Parties>
<Invoices><Invoice><InvoiceHeader><InvoiceClass>{kind}</InvoiceClass><InvoiceNumber>{number}</InvoiceNumber></InvoiceHeader>
<InvoiceIssueData><IssueDate>2031-11-01</IssueDate><InvoiceCurrencyCode>EUR</InvoiceCurrencyCode>
<ReceiverTransactionReference>ORDER-OTHER</ReceiverTransactionReference></InvoiceIssueData>
<InvoiceTotals><TotalGrossAmountBeforeTaxes>10.00</TotalGrossAmountBeforeTaxes><TotalTaxOutputs>2.10</TotalTaxOutputs>
<TotalTaxesWithheld>0.00</TotalTaxesWithheld><InvoiceTotal>12.10</InvoiceTotal></InvoiceTotals>
</Invoice></Invoices></Facturae>'''


class APSourcePlanTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.phase, self.prepared = self.root / "phase", self.root / "prepared"
        (self.phase / "tasks").mkdir(parents=True)
        (self.phase / "erp").mkdir()
        self.ids = ["READY-NEW", "XML-NEW", "FAILED-NEW", "EMPTY-NEW", "CREDIT-NEW", "MULTI-NEW"]
        (self.phase / "tasks/close.json").write_text('{"month":"2031-11"}')
        (self.phase / "tasks/ap_documents.json").write_text(json.dumps(self.ids))
        self.write("vendors", [dict(id="SUPPLIER-OTHER", tax_id="SUPPLIERTAX", companies=["COMPANY-OTHER"], po_required=True)])
        self.write("purchase_orders", [dict(id="ORDER-OTHER", company="COMPANY-OTHER", vendor="SUPPLIER-OTHER",
            currency="EUR", created_on="2031-10-01", items=[dict(item=40, uom="hours", unit_price=1000)])])
        self.write("goods_receipts", [dict(id="RECEIPT-OTHER", company="COMPANY-OTHER", vendor="SUPPLIER-OTHER",
            po="ORDER-OTHER", po_item=40, type="SES", quantity_milli=2000, amount=2000, posting_date="2031-11-05")])
        for table in ("ap_invoices", "ap_document_log", "journal_entries"):
            self.write(table, [])
        (self.phase / "erp/companies.json").write_text(json.dumps([
            dict(code="COMPANY-OTHER", tax_id="BUYERTAX", country="ES")]))
        self.config = RecordingConfig("synthetic", "fixture-model", "context-fixture-v1", "prompt-v1",
            "a" * 64, "schema-v1", "b" * 64, parameters={"temperature": 0.25})
        self.store = RecordingStore(self.root / "captures")
        self.sources("READY-NEW", {"invoice.txt": self.invoice_text("NEW-NUMBER")})
        self.sources("XML-NEW", {"invoice.xml": XML.format(kind="OO", number="XML-NUMBER")})
        self.sources("FAILED-NEW", {"uninterpreted.txt": "uninterpreted original attachment"})
        self.sources("CREDIT-NEW", {"credit.xml": XML.format(kind="OR", number="CREDIT-NUMBER")})
        self.sources("MULTI-NEW", {"invoice.txt": self.invoice_text("MULTI-NUMBER"),
            "invoice.xml": XML.format(kind="OO", number="MULTI-NUMBER")})
        self.capture("READY-NEW", "NEW-NUMBER")
        self.capture("MULTI-NEW", "MULTI-NUMBER")
        extractor = RecordedExtractor(self.store, self.config, mode="fixture")
        self.run = await prepare_ap_sources(self.phase, self.prepared, mode="fixture", extractor=extractor)
        self.cutoff = Fact("2031-11-20", Evidence("tasks/close.json", "observed cutoff for synthetic fixture"))

    def write(self, table, rows):
        (self.phase / "erp" / (table + ".jsonl")).write_text("".join(json.dumps(row) + "\n" for row in rows))

    @staticmethod
    def invoice_fields(number):
        return {"document_type_hint": "Invoice", "supplier_tax_id": "SUPPLIERTAX",
            "recipient_tax_id": "BUYERTAX", "document_number": number, "document_date": "2031-11-01",
            "currency": "EUR", "net_cents": 1000, "tax_cents": 210, "gross_cents": 1210,
            "po_reference": "ORDER-OTHER", "line.1.po_item": 40, "line.1.quantity_milli": 1000,
            "line.1.uom": "hours", "line.1.unit_price_e4": 100000}

    def invoice_text(self, number):
        return "\n".join(f"{name}: {value}" for name, value in self.invoice_fields(number).items())

    def sources(self, doc_id, contents):
        folder = self.phase / "inbox/ap" / doc_id
        folder.mkdir(parents=True)
        (folder / "message.json").write_text(json.dumps(dict(doc_id=doc_id, channel="EMAIL",
            received_at="2031-11-10T09:30:00Z", attachments=list(contents), subject="Invoice",
            body="Original message", supplier_extra_metadata={"received_by": "receiver"})))
        for name, content in contents.items():
            (folder / name).write_text(content)

    def capture(self, doc_id, number):
        relative = f"inbox/ap/{doc_id}/invoice.txt"
        parsed = DocumentRouter(self.phase).parse(relative)
        block = parsed.blocks[0]
        facts = DocumentFacts(parsed.source_sha256, self.config.extractor_version,
            {name: [Fact(value, Evidence(relative, block.source_field or block.id, block.page, str(value)))]
             for name, value in self.invoice_fields(number).items()})
        self.store.save("extract", parsed, self.config, ExtractionCapture(facts, {}, {}), origin="synthetic")

    def originals(self):
        return {path.relative_to(self.phase).as_posix(): digest(path.read_bytes())
                for path in self.phase.rglob("*") if path.is_file()}

    async def test_full_inventory_retains_unknown_unsupported_and_multi_source_tasks(self):
        before = self.originals()
        plan = await plan_ap_sources(self.phase, self.run.manifest_path, receipt_as_of=self.cutoff)
        self.assertEqual(plan["task_keys"], self.ids)
        self.assertEqual([task["task_key"] for task in plan["tasks"]], self.ids)
        by_id = {task["task_key"]: task for task in plan["tasks"]}
        self.assertEqual(by_id["READY-NEW"]["status"], "READY_CONTEXT")
        self.assertEqual(by_id["CREDIT-NEW"]["status"], "UNSUPPORTED")
        self.assertEqual(by_id["EMPTY-NEW"]["attachments"], [])
        self.assertEqual(by_id["EMPTY-NEW"]["status"], "UNKNOWN")
        self.assertTrue(by_id["EMPTY-NEW"]["source_diagnostics"])
        self.assertEqual(by_id["FAILED-NEW"]["attachments"][0]["source_role"], "UNKNOWN")
        self.assertIsNone(by_id["FAILED-NEW"]["attachments"][0]["normalized_facts"])
        self.assertEqual(len(by_id["MULTI-NEW"]["attachments"]), 2)
        self.assertEqual(by_id["MULTI-NEW"]["status"], "UNKNOWN")
        self.assertIsNone(by_id["MULTI-NEW"]["context"]["primary_source"])
        self.assertEqual(plan["summary"]["task_count"], len(self.ids))
        self.assertEqual(sum(plan["summary"]["statuses"].values()), len(self.ids))
        self.assertEqual(plan["source_manifest"]["mode"], "fixture")
        self.assertEqual(by_id["READY-NEW"]["attachments"][0]["capture_origin"], "synthetic")
        self.assertFalse(plan["run"]["accounting_run"])
        self.assertFalse(plan["run"]["exportsAP"])
        self.assertEqual(plan["run"]["credits_opening_status"], "NOT_EVALUATED")
        self.assertEqual(plan["run"]["advances_opening_status"], "NOT_EVALUATED")
        self.assertTrue(all(task["fiscal_decision_status"] == "NOT_EVALUATED" for task in plan["tasks"]))
        self.assertTrue(all(task["monetary_posting_status"] == "NOT_EVALUATED" for task in plan["tasks"]))
        self.assertEqual(before, self.originals())

    async def test_no_cutoff_is_inferred_and_ready_context_never_creates_posting_inputs(self):
        plan = await plan_ap_sources(self.phase, self.run.manifest_path)
        ready = plan["tasks"][0]
        self.assertEqual(ready["status"], "UNKNOWN")
        self.assertIn("RECEIPT_CUTOFF_UNKNOWN", ready["context"]["diagnostics"])
        self.assertIsNone(plan["observed_receipt_cutoff"])
        self.assertFalse(ready["context"]["request_summary"]["header_available"])
        self.assertFalse(ready["context"]["request_summary"]["posting_available"])
        with self.assertRaises(TypeError):
            await plan_ap_sources(self.phase, self.run.manifest_path, receipt_as_of="2031-11-20")

    async def test_replay_has_stable_identity_with_no_network_or_capture_or_extraction(self):
        def forbidden(*args, **kwargs):
            raise AssertionError("source audit cannot call network or interpretation")
        with patch.object(socket.socket, "connect", forbidden), patch.object(socket, "create_connection", forbidden), \
                patch.object(RecordedExtractor, "__init__", forbidden), \
                patch("kalmora.documents.xml_extractor.XMLDocumentExtractor.extract", forbidden):
            first = await plan_ap_sources(self.phase, self.run.manifest_path, receipt_as_of=self.cutoff)
            manifest = json.loads(self.run.manifest_path.read_text())
            manifest["report"]["new_provider_calls"] = 99
            manifest["report"]["new_provider_cost_usd"] = "999.00"
            self.run.manifest_path.write_text(json.dumps(manifest))
            second = await plan_ap_sources(self.phase, self.run.manifest_path, receipt_as_of=self.cutoff)
        self.assertEqual(first["stable_plan_sha256"], second["stable_plan_sha256"])
        self.assertNotEqual(first["execution"]["manifest_sha256"], second["execution"]["manifest_sha256"])
        self.assertEqual({key: value for key, value in first.items() if key != "execution"},
                         {key: value for key, value in second.items() if key != "execution"})
        stable = {key: value for key, value in first.items() if key not in {"execution", "stable_plan_sha256"}}
        self.assertEqual(first["stable_plan_sha256"], fingerprint(stable))
        self.assertEqual(first["execution"]["new_provider_calls"], 0)
        self.assertEqual(first["execution"]["new_provider_cost_usd"], "0")
        decoded = json.loads(json.dumps(first, allow_nan=False))
        raw = DocumentFacts.from_dict(decoded["tasks"][0]["attachments"][0]["raw_facts"])
        self.assertEqual(raw.fields["gross_cents"][0].value, 1210)
        self.assertEqual(decoded["tasks"][0]["context"]["lines"][0]["uom"]["value"], "hours")

    async def test_order_catalogue_is_verified_and_built_once_for_the_whole_batch(self):
        original = APOrderBridge.from_phase
        with patch.object(APOrderBridge, "from_phase", side_effect=original) as build:
            plan = await plan_ap_sources(self.phase, self.run.manifest_path, receipt_as_of=self.cutoff)
        self.assertEqual(build.call_count, 1)
        self.assertEqual(plan["active_erp"]["historical_receipts"]["count"], 1)
        self.assertTrue(any(source["path"] == "erp/companies.json" for source in plan["active_erp"]["sources"]))

    async def test_batch_rejects_changed_master_after_context_resolution(self):
        changed = False
        async def mutate(*args, **kwargs):
            nonlocal changed
            result = await resolve_ap_invoice_context(*args, **kwargs)
            if not changed:
                changed = True
                self.write("vendors", [dict(id="SUPPLIER-OTHER", tax_id="OTHER-TAX")])
            return result
        with patch("kalmora.ap_source_plan.resolve_ap_invoice_context", side_effect=mutate):
            with self.assertRaisesRegex(ValueError, "batch sources changed"):
                await plan_ap_sources(self.phase, self.run.manifest_path, receipt_as_of=self.cutoff)

    async def test_batch_rejects_original_or_artifact_mutation_and_golden_manifest(self):
        original = self.phase / "inbox/ap/XML-NEW/invoice.xml"
        saved = original.read_bytes()
        changed = False
        async def mutate_original(*args, **kwargs):
            nonlocal changed
            result = await resolve_ap_invoice_context(*args, **kwargs)
            if not changed:
                changed = True
                original.write_bytes(saved.replace(b"XML-NUMBER", b"MUTATED-NUMBER"))
            return result
        with patch("kalmora.ap_source_plan.resolve_ap_invoice_context", side_effect=mutate_original):
            with self.assertRaises(ValueError):
                await plan_ap_sources(self.phase, self.run.manifest_path, receipt_as_of=self.cutoff)
        original.write_bytes(saved)
        artifact = self.prepared / self.run.manifest["documents"][0]["attachments"][0]["artifact"]
        saved_artifact = artifact.read_bytes()
        async def mutate_artifact(*args, **kwargs):
            result = await resolve_ap_invoice_context(*args, **kwargs)
            artifact.write_bytes(saved_artifact + b" ")
            return result
        with patch("kalmora.ap_source_plan.resolve_ap_invoice_context", side_effect=mutate_artifact):
            with self.assertRaisesRegex(ValueError, "artifact changed"):
                await plan_ap_sources(self.phase, self.run.manifest_path)
        artifact.write_bytes(saved_artifact)
        golden = self.root / "golden"
        golden.mkdir()
        manifest = golden / "phase-sources.json"
        manifest.write_bytes(self.run.manifest_path.read_bytes())
        with self.assertRaisesRegex(ValueError, "Golden"):
            await plan_ap_sources(self.phase, manifest)

    async def test_configuration_mutation_is_rejected_before_any_context_is_built(self):
        manifest = deepcopy(self.run.manifest)
        manifest["configuration"]["source_runner"] = "old-source-runner"
        self.run.manifest_path.write_text(json.dumps(manifest))
        with patch("kalmora.ap_source_plan.resolve_ap_invoice_context") as build:
            with self.assertRaisesRegex(ValueError, "configuration versions"):
                await plan_ap_sources(self.phase, self.run.manifest_path)
        build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
