"""AR source coverage and strict replay, using original synthetic text documents."""
import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from kalmora.billing.io import write_billing
from kalmora.billing.source_runner import build_billing_from_sources
from kalmora.data import PhaseData
from kalmora.documents.contracts import ResolutionResult, digest, fingerprint
from kalmora.documents.prompts import recording_prompt
from kalmora.documents.replay import RecordingConfig, ResolutionCapture
from kalmora.facts import DocumentFacts


CERTIFICATE = """CERTIFICACIÓN DE OBRA Nº 01
Contrato: CV-NEW · Promotor / cliente: Municipio
Mes certificado: 2026-07
Cap.    Descripción (relación valorada del mes)    Importe del mes
01      Capítulo 01 – Estructura                 100,00 EUR
Certificado a origen: 100,00 EUR
Certificado anterior: 0,00 EUR
Importe de la presente certificación: 100,00 EUR
Importes sin impuestos. CONFORME
Dirección Facultativa – Ingeniero
"""


class BillingSourceRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.phase, self.work = self.root / "phase", self.root / "state"
        (self.phase / "tasks").mkdir(parents=True)
        (self.phase / "erp").mkdir()
        (self.phase / "tasks/close.json").write_text('{"month":"2026-07"}')
        (self.phase / "tasks/ar_billing_items.json").write_text('["OPAQUE-ITEM"]')
        self.folder = self.phase / "inbox/ar/billing/OPAQUE-ITEM"
        self.folder.mkdir(parents=True)
        self.metadata = dict(billing_item="OPAQUE-ITEM", type="OBRA_CERTIFICATION", company="1100",
                             contract="CV-NEW", customer="C1", month="2026-07", documents=["source.txt"])
        self.write_metadata()
        (self.folder / "source.txt").write_text(CERTIFICATE)
        tables = {
            "companies": [{"code": "1100", "country": "ES", "currency": "EUR"}],
            "tax_codes": {"tax_codes": {"R21": {"kind": "output", "country": "ES", "rate": 2100}}},
            "customers": [{"id": "C1", "name": "Municipio", "kind": "public", "country": "ES",
                           "dir3": {"oficina_contable": "D1", "organo_gestor": "D2", "unidad_tramitadora": "D3"}}],
            "cost_centers": [],
            "projects": [{"id": "OB-NEW", "company": "1100", "wbs": [{"id": "OB-NEW.01"}]}],
            "sales_contracts": [{"id": "CV-NEW", "name": "Contrato nuevo", "company": "1100",
                                 "customer": "C1", "kind": "obra_cert", "project": "OB-NEW",
                                 "tax": "R21", "terms_days": 30, "retention_bp": 0}],
            "ar_invoices": [], "billing_history": []}
        for name, rows in tables.items():
            (self.phase / f"erp/{name}.json").write_text(json.dumps(rows))

    def write_metadata(self):
        (self.folder / "item.json").write_text(json.dumps(self.metadata))

    async def build(self, **options):
        return await build_billing_from_sources(PhaseData(self.phase), work_dir=self.work, **options)

    async def test_native_record_and_replay_preserve_literals_and_publish_both_deliverables(self):
        record, replay = await self.build(), await self.build(mode="replay")
        self.assertTrue(record.complete)
        self.assertEqual(record.stable_sha256, replay.stable_sha256)
        self.assertEqual(record.billing, replay.billing)
        self.assertEqual(replay.report["new_provider_calls"], 0)
        self.assertEqual(replay.report["new_provider_cost_usd"], "0")
        packet, = replay.report["items"]
        self.assertEqual(packet["metadata"]["value"], self.metadata)
        artifact = json.loads((self.work / packet["attachments"][0]["artifact"]).read_text())
        literals = DocumentFacts.from_dict(artifact["extraction"]["value"])
        self.assertEqual(literals.fields["current_amount"][0].value, "100,00")
        self.assertEqual(artifact["normalized"]["facts"]["fields"]["current_cents"][0]["value"], 10000)
        output = write_billing(replay.billing, self.root / "delivery")
        self.assertTrue((output / "ar_billing.jsonl").is_file())
        self.assertTrue((output / "pending_wip.jsonl").is_file())

    async def test_missing_and_changed_sources_remain_unresolved_in_replay(self):
        missing = await self.build(mode="replay")
        self.assertFalse(missing.complete)
        self.assertEqual(missing.billing.results, ())
        self.assertIn("missing", missing.billing.unresolved[0].reasons[0])
        await self.build()
        (self.folder / "source.txt").write_text(CERTIFICATE.replace("100,00", "200,00"))
        changed = await self.build(mode="replay")
        self.assertFalse(changed.complete)
        self.assertEqual(changed.report["coverage"]["unresolved_count"], 1)

    async def test_normalizer_version_change_invalidates_capture_without_replay_fallback(self):
        self.assertTrue((await self.build()).complete)
        with patch("kalmora.billing.extraction.AR_NORMALIZATION_VERSION", "new-normalization-contract"), \
                patch("kalmora.billing.extraction.NativeBillingExtractor.extract_with_response",
                      side_effect=AssertionError("replay must not invoke an extractor callback")) as callback:
            replay = await self.build(mode="replay")
        self.assertFalse(replay.complete)
        self.assertEqual(replay.billing.results, ())
        self.assertIn("missing", replay.billing.unresolved[0].reasons[0])
        self.assertEqual(replay.report["new_provider_calls"], 0)
        callback.assert_not_called()

    async def test_semantic_record_and_replay_bind_source_facts_and_current_phase_context(self):
        alias = "Municipio (abreviado)"
        (self.folder / "source.txt").write_text(CERTIFICATE.replace(
            "Municipio\n", alias + "\nContratista: Kalmora Infraestructura\n"))
        config = RecordingConfig("local-test", "local-semantic", "semantic-test-v1", "prompt-test-v1",
                                 digest(b"instructions"), "schema-test-v1", digest(b"schema"),
                                 {"max_selections": 1})
        requests = []

        class LocalResponseAdapter:
            async def resolve_with_response(adapter, request):
                requests.append(request)
                candidate, = request.candidates
                block = request.document.blocks[0]
                result = ResolutionResult("SELECTED", (candidate.id,), ({
                    "candidate_id": candidate.id, "candidate_attribute": "name",
                    "candidate_value": candidate.attributes["name"], "source_value": alias,
                    "block_id": block.id, "quote": "Promotor / cliente: " + alias,
                    "source_sha256": request.document.source_sha256},), "source abbreviation of eligible customer")
                metadata = {"provider": config.provider, "model": config.model,
                    "prompt_version": config.prompt_version,
                    "instructions_sha256": config.prompt_sha256,
                    "instruction_content_sha256": config.prompt_sha256,
                    "prompt_sha256": digest(recording_prompt("resolve", request, config.parameters).encode()),
                    "schema_sha256": config.schema_sha256, "schema_version": config.schema_version,
                    "source_sha256": request.document.source_sha256,
                    "parser_version": request.document.parser_version,
                    "transformation_sha256": request.document.transformation_sha256,
                    "resolution_request_sha256": request.sha256,
                    "capture_cost_usd": "0", "attempt_metrics": []}
                return ResolutionCapture(result, {"status": "completed"}, metadata)

        record = await self.build(semantic_resolver=LocalResponseAdapter(), resolver_config=config,
                                  budget_usd=Decimal("0.01"))
        self.assertTrue(record.complete)
        self.assertEqual(len(requests), 1)
        request, = requests
        packet, = record.report["items"]
        artifact = json.loads((self.work / packet["attachments"][0]["artifact"]).read_text())
        literals = DocumentFacts.from_dict(artifact["extraction"]["value"])
        self.assertEqual(request.context["_extraction_sha256"], fingerprint(literals.to_dict()))
        self.assertEqual(request.context["_phase"], self.phase.name)
        self.assertEqual(request.context["_run_context_sha256"], fingerprint(record.report["context"]))
        with patch.object(LocalResponseAdapter, "resolve_with_response",
                          side_effect=AssertionError("replay cannot call the semantic adapter")) as callback:
            replay = await self.build(mode="replay", resolver_config=config)
        callback.assert_not_called()
        self.assertEqual(record.billing, replay.billing)
        self.assertEqual(record.stable_sha256, replay.stable_sha256)
        self.assertTrue(replay.report["resolution_captures"][0]["provenance"]["cache_hit"])
        self.assertEqual(replay.report["new_provider_calls"], 0)
        self.assertEqual(replay.report["new_provider_cost_usd"], "0")
        contracts = self.phase / "erp/sales_contracts.json"
        rows = json.loads(contracts.read_text())
        rows[0]["name"] = "Changed current master context"
        contracts.write_text(json.dumps(rows))
        stale = await self.build(mode="replay", resolver_config=config)
        self.assertFalse(stale.complete)
        self.assertIn("missing", stale.billing.unresolved[0].reasons[0])
        self.assertEqual(len(requests), 1)

    async def test_missing_declared_source_and_metadata_are_independent_coverage_failures(self):
        self.metadata["documents"].append("absent.pdf")
        self.write_metadata()
        result = await self.build()
        self.assertFalse(result.complete)
        self.assertEqual(len(result.report["items"][0]["attachments"]), 2)
        self.assertIn("MISSING_DOCUMENT_SOURCE", result.billing.unresolved[0].reasons[0])
        (self.folder / "item.json").unlink()
        missing = await self.build()
        self.assertFalse(missing.complete)
        self.assertEqual(missing.report["coverage"]["task_count"], 1)
        self.assertEqual(missing.report["items"][0]["diagnostics"][0]["code"], "INVALID_ITEM_METADATA")

    async def test_multiple_originals_keep_each_origin_and_conflicts_block_billing(self):
        (self.folder / "copy.txt").write_text(CERTIFICATE)
        self.metadata["documents"].append("copy.txt")
        self.write_metadata()
        equal = await self.build()
        self.assertTrue(equal.complete)
        self.assertEqual(len(equal.billing.results), 1)
        self.assertEqual({e.document for e in equal.billing.results[0].evidence},
                         {"inbox/ar/billing/OPAQUE-ITEM/source.txt", "inbox/ar/billing/OPAQUE-ITEM/copy.txt"})
        (self.folder / "copy.txt").write_text(CERTIFICATE.replace("100,00", "200,00"))
        conflict = await self.build()
        self.assertFalse(conflict.complete)
        self.assertIn("CONFLICT", conflict.billing.unresolved[0].reasons[0])

    async def test_complementary_supports_combine_only_located_source_facts(self):
        (self.folder / "source.txt").write_text(CERTIFICATE.replace("Mes certificado: 2026-07\n", ""))
        (self.folder / "period.txt").write_text("Mes certificado: 2026-07\n")
        self.metadata["documents"].append("period.txt")
        self.write_metadata()
        result = await self.build()
        self.assertTrue(result.complete)
        self.assertTrue(any(e.document.endswith("period.txt") for e in result.billing.results[0].evidence))

    async def test_pending_approval_supplies_close_input_without_invoice(self):
        (self.folder / "source.txt").write_text(CERTIFICATE.replace("CONFORME", "PENDIENTE DE APROBACIÓN"))
        result = await self.build()
        self.assertTrue(result.complete)
        self.assertIsNone(result.billing.results[0].invoice)
        self.assertEqual(len(result.billing.pending_wip), 1)
        self.assertEqual(result.billing.pending_wip[0].amount, 10000)

    async def test_artifact_destinations_cannot_modify_originals(self):
        with self.assertRaisesRegex(ValueError, "outside original"):
            await build_billing_from_sources(PhaseData(self.phase), work_dir=self.phase / "state")
        self.work.mkdir()
        (self.work / "recordings").symlink_to(self.phase)
        with self.assertRaisesRegex(ValueError, "escapes"):
            await self.build()


if __name__ == "__main__":
    unittest.main()
