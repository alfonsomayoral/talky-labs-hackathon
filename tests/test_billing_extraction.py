import unittest
import hashlib
from decimal import Decimal
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from kalmora.billing.extraction import LLMBillingExtractor, NativeBillingExtractor, normalize_billing_facts
from kalmora.billing.model import BillingType
from kalmora.documents.contracts import ParsedBlock, ParsedDocument, digest
from kalmora.documents.replay import RecordedExtractor, RecordingConfig, RecordingStore, ReplayError
from kalmora.documents.extractor import DocumentInterpretationError
from kalmora.facts import DocumentFacts

try:
    import pydantic
except ImportError:
    pydantic = None


def document(text):
    return ParsedDocument("inbox/ar/billing/BILL-1/documento.pdf", digest(text.encode()),
                          "application/pdf", "test-reader-v1", (ParsedBlock("page.1", text, 1),))


CERTIFICATION = """CERTIFICACIÓN DE OBRA Nº 02
Contrato: CV-OB-1100-01 · Promotor / cliente: Promotor Uno
Contratista: Kalmora Construcción
Mes certificado: 2026-07
Cap.    Descripción (relación valorada del mes)    Importe del mes
01      Capítulo 01 – Estructura                 1.234,56 EUR
02      Capítulo 02 – Instalaciones              2.345,67 EUR
Certificado a origen: 4.580,23 EUR
Certificado anterior: 1.000,00 EUR
Importe de la presente certificación: 3.580,23 EUR
Importes sin impuestos. CONFORME
Dirección Facultativa – Arquitecto
"""

SERVICE = """PARTE MENSUAL DE SERVICIO – CONFORMIDAD MUNICIPAL
Contrato: Limpieza de Calle (CT-1200-01)
Cliente: Ayuntamiento Uno
Mes: 2026-07
Concepto               Orden        Importe (sin IVA)        Estado
Canon mensual          —            100,00 EUR               CONFORMEConforme
Limpieza extraordinaria  ORD-1       12,00 EUR                Conforme
Recogida adicional       ORD-2       25,00 EUR                PENDIENTE DE CONFORMIDAD
Los servicios extraordinarios sólo pueden facturarse con conformidad. Técnico municipal
"""

REVISION = """AYUNTAMIENTO DE UNO
Decreto de Alcaldía 2026/15
Visto el contrato «Limpieza de Calle», RESUELVO: aprobar la revisión de precios con efectos 2026-01-01,
fijando el nuevo canon mensual en 120,00 EUR (anterior: 100,00 EUR), IVA no incluido.
El contratista podrá facturar las diferencias devengadas desde la fecha de efectos (2026-01, 2026-02).
Fecha de aprobación: 2026-03-01
EL ALCALDE-PRESIDENTE
Firmado electrónicamente
"""

PPA = """INFORME MENSUAL DE PRODUCCIÓN – MEDIDA FISCAL
Periodo: 2026-06 · Contrato PPA PPA-1300-01 · Comprador: Comercializadora Uno
Planta                              Energía neta medida (MWh)
PSF Planta I (49,9 MWp)              8.652,582
PSF Planta II                       5.783,133
Porcentaje de la producción contratada en el PPA: 70 % · Precio fijo: 41.505 €/MWh (sin IVA)
"""

MARKET = """REPRESENTANTE UNO
LIQUIDACIÓN MENSUAL DE VENTA DE ENERGÍA EN MERCADO
Periodo 2026-06 · Titular: Kalmora Energía
Planta                             MWh vendidos             Importe (€)
PSF Planta I (49,9 MWp)             2,737.647                197.781,33 EUR
PSF Planta II                      1,787.667                129.150,01 EUR
Precio medio ponderado: 72.25 €/MWh · Coste de desvíos imputado: -14.603,36 EUR
"""


class BillingExtractionTests(unittest.IsolatedAsyncioTestCase):
    async def extract(self, kind, text):
        source = document(text)
        capture = await NativeBillingExtractor(kind).extract_with_response(source)
        observations = normalize_billing_facts(kind, capture.facts, source)
        return source, capture, observations

    async def test_certification_preserves_literal_and_architect_role(self):
        _, capture, normalized = await self.extract(BillingType.OBRA_CERTIFICATION, CERTIFICATION)
        self.assertEqual(capture.facts.fields["current_amount"][0].value, "3.580,23")
        self.assertEqual(normalized.facts.fields["current_cents"][0].value, 358023)
        self.assertEqual(capture.facts.fields["authority_text"][0].value, "Dirección Facultativa – Arquitecto")
        self.assertEqual(normalized.facts.fields["authority_text"][0].value, "DIRECCIÓN FACULTATIVA – ARQUITECTO")
        self.assertEqual(normalized.row_counts, {"chapter": 2})
        self.assertEqual(capture.request_metadata["provider_calls"], 0)

    async def test_service_keeps_pending_extra_and_explicit_empty_table(self):
        _, capture, normalized = await self.extract(BillingType.SERVICE_MONTHLY, SERVICE)
        self.assertEqual(normalized.row_counts, {"extra": 2})
        self.assertEqual(normalized.facts.fields["extra.2.status_text"][0].value, "PENDIENTE DE CONFORMIDAD")
        self.assertEqual(capture.facts.fields["canon_status_text"][0].value, "CONFORMEConforme")
        empty = "\n".join(line for line in SERVICE.splitlines() if not line.startswith(("Limpieza extraordinaria", "Recogida adicional")))
        _, _, normalized = await self.extract(BillingType.SERVICE_MONTHLY, empty)
        self.assertEqual(normalized.row_counts, {"extra": 0})

    async def test_service_policy_sentence_does_not_supply_a_missing_signer(self):
        text = SERVICE.replace(" Técnico municipal\n", "\n")
        text += "Sólo con la conformidad del técnico municipal responsable del contrato.\n"
        _, capture, normalized = await self.extract(BillingType.SERVICE_MONTHLY, text)
        self.assertNotIn("authority_text", capture.facts.fields)
        self.assertNotIn("authority_text", normalized.facts.fields)

    async def test_revision_uses_printed_months_and_keeps_signature(self):
        _, capture, normalized = await self.extract(BillingType.PRICE_REVISION, REVISION)
        self.assertEqual(normalized.row_counts, {"revision_month": 2})
        self.assertEqual(capture.facts.fields["signature_text"][0].value, "Firmado electrónicamente")
        self.assertNotIn("contract_reference", capture.facts.fields)
        self.assertNotIn("authority_text", normalized.facts.fields)

    async def test_energy_uses_explicit_different_mwh_locales_and_signed_cost(self):
        _, _, ppa = await self.extract(BillingType.PPA, PPA)
        self.assertEqual(ppa.facts.fields["plant.1.mwh_milli"][0].value, 8652582)
        self.assertEqual(Decimal(ppa.facts.fields["price_mwh_cents"][0].value), Decimal("4150.500"))
        self.assertEqual(ppa.facts.fields["share_bp"][0].value, 7000)
        self.assertEqual(ppa.facts.fields["currency"][0].value, "EUR")
        _, _, market = await self.extract(BillingType.MARKET_SETTLEMENT, MARKET)
        self.assertEqual(market.facts.fields["plant.1.mwh_milli"][0].value, 2737647)
        self.assertEqual(market.facts.fields["deviations_cents"][0].value, -1460336)

    async def test_unparsed_row_cannot_claim_complete_table(self):
        malformed = CERTIFICATION.replace("2.345,67", "2,345.67")
        source = document(malformed)
        capture = await NativeBillingExtractor(BillingType.OBRA_CERTIFICATION).extract_with_response(source)
        with self.assertRaisesRegex(ValueError, "table row"):
            normalize_billing_facts(BillingType.OBRA_CERTIFICATION, capture.facts, source)

    async def test_missing_stamp_is_unknown_and_conflicts_are_preserved(self):
        source, capture, normalized = await self.extract(BillingType.OBRA_CERTIFICATION, CERTIFICATION.replace(" CONFORME", ""))
        self.assertIn({"field": "status_text", "status": "MISSING", "reason": "literal field not found in native source"}, capture.unknowns)
        self.assertNotIn("status_text", normalized.facts.fields)
        conflicting = CERTIFICATION + "PENDIENTE DE APROBACIÓN\n"
        _, _, normalized = await self.extract(BillingType.OBRA_CERTIFICATION, conflicting)
        self.assertEqual({fact.value for fact in normalized.facts.fields["status_text"]}, {"CONFORME", "PENDIENTE DE APROBACIÓN"})

    async def test_wrapped_customer_name_stays_complete_despite_page_fragments(self):
        from dataclasses import replace
        text = CERTIFICATION.replace("Promotor Uno", "Secretaría de Infraestructura de Nuevo\nValle")
        source = document(text)
        source = replace(source, blocks=source.blocks +
                         (ParsedBlock("page.1.fragment.1", "Promotor / cliente: Secretaría de Infraestructura de Nuevo", 1),))
        capture = await NativeBillingExtractor(BillingType.OBRA_CERTIFICATION).extract_with_response(source)
        self.assertEqual([fact.value for fact in capture.facts.fields["customer_name"]],
                         ["Secretaría de Infraestructura de Nuevo\nValle"])

    async def test_replay_uses_literal_capture_and_rejects_different_source(self):
        source = document(PPA)
        extractor = NativeBillingExtractor(BillingType.PPA)
        config = RecordingConfig.from_adapter(extractor)
        with TemporaryDirectory() as directory:
            store = RecordingStore(directory)
            capture = await extractor.extract_with_response(source)
            store.save("extract", source, config, capture)
            replay = RecordedExtractor(store, config, mode="replay")
            result = await replay.extract_with_response(source)
            self.assertEqual(result.facts.fields["plant.1.mwh"][0].value, "8.652,582")
            self.assertEqual(result.provenance["new_provider_calls"], 0)
            self.assertEqual(normalize_billing_facts(BillingType.PPA, result.facts, source).row_counts, {"plant": 2})
            with self.assertRaises(ReplayError):
                await replay.extract(document(PPA.replace("8.652,582", "8.652,583")))

    async def test_partial_capture_does_not_shrink_source_table_count(self):
        source, capture, _ = await self.extract(BillingType.OBRA_CERTIFICATION, CERTIFICATION)
        partial = DocumentFacts(capture.facts.source_sha256, capture.facts.extractor_version,
                                {key: values for key, values in capture.facts.fields.items()
                                 if not key.startswith("chapter.2.")})
        normalized = normalize_billing_facts(BillingType.OBRA_CERTIFICATION, partial, source)
        self.assertEqual(normalized.row_counts, {"chapter": 2})
        self.assertNotIn("chapter.2.amount_cents", normalized.facts.fields)

    @unittest.skipIf(pydantic is None, "optional LLM DTO requires pydantic")
    async def test_optional_llm_adapter_records_literal_success_and_failed_grounding(self):
        source = document(CERTIFICATION)
        native = await NativeBillingExtractor(BillingType.OBRA_CERTIFICATION).extract_with_response(source)
        observations = [{"field": name, "value": fact.value, "kind": "OBSERVED",
                         "block_id": "page.1", "quote": fact.evidence.quote,
                         "image_page": None, "image_sha256": None}
                        for name, candidates in native.facts.fields.items() for fact in candidates]

        class Client:
            config = SimpleNamespace(model="injected-test", reasoning_effort="low", max_input_tokens=100,
                                     max_output_tokens=100, image_token_reserve=100, max_image_bytes=100,
                                     image_detail="auto", model_output_capacity_tokens=100)
            provider = object()

            async def complete(self, schema, instructions, prompt, **kwargs):
                return SimpleNamespace(output=schema.model_validate({"observations": observations, "unknowns": []}),
                                       raw_response={"status": "completed", "id": "injected-success"},
                                       request_metadata={"instructions_sha256": hashlib.sha256(instructions.encode()).hexdigest(),
                                                         "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
                                                         "capture_cost_usd": "0", "attempt_metrics": []})

        extractor = LLMBillingExtractor(BillingType.OBRA_CERTIFICATION, Client())
        capture = await extractor.extract_with_response(source)
        with TemporaryDirectory() as directory:
            store = RecordingStore(directory)
            config = RecordingConfig.from_adapter(extractor)
            store.save("extract", source, config, capture)
            replay = RecordedExtractor(store, config, mode="replay")
            loaded = await replay.extract_with_response(source)
            self.assertEqual(loaded.facts.fields["current_amount"][0].value, "3.580,23")
        observations[0]["value"] = "not in the source"
        with self.assertRaises(DocumentInterpretationError) as caught:
            await extractor.extract_with_response(source)
        self.assertEqual(caught.exception.raw_response["id"], "injected-success")
        self.assertEqual(caught.exception.request_metadata["capture_cost_usd"], "0")


if __name__ == "__main__":
    unittest.main()
