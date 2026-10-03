import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from kalmora.documents.contracts import ParsedBlock, ParsedDocument, ProcessingAid, PageImage, digest
from kalmora.documents.composition import compose_native_invoice
from kalmora.facts import DocumentFacts, Evidence, Fact
from kalmora.documents.extractor import ExtractionArtifact
from kalmora.documents.replay import RecordingStore
from tools import capture_document_sample
from tools.evaluate_document_sample import captured_document, composed_facts


def fixture_args(root, output, manifest, **overrides):
    values = dict(participant_root=root, output=output, manifest=manifest,
        partition='tuning', case=None, budget=__import__('decimal').Decimal('1'),
        model='fixture-model', reasoning_effort='low', timeout_seconds=None,
        max_output_tokens=None, image_detail='high', max_input_tokens=200_000,
        page_strips=False, validation_attempts=1, transport_attempts=2,
        require_line_descriptions=False, pdf_ocr=False, renderer_only=False,
        native_tables=True, require_page_coverage=False, require_native_row_coverage=False,
        omit_ocr_aids=False, pdf_renderer=None, tesseract=None,
        input_usd_per_million=__import__('decimal').Decimal('0.125'),
        output_usd_per_million=__import__('decimal').Decimal('0.50'),
        pricing_provenance='test_fixture', semantic=False)
    values.update(overrides)
    return SimpleNamespace(**values)


class TestFixtureTransport:
    """No network implementation; carries the same request config for integration tests."""
    calls = 0

    def __init__(self, config, recorder):
        self.config = config
        self.provider = None
        recorder.report['llm_budget'] = {
            'currency': 'USD', 'limit': str(config.budget_usd), 'known_cost': '0',
            'pending_reservations': '0', 'unknown_reservations': '0',
            'available': str(config.budget_usd)}

    async def complete(self, *args, **kwargs):
        type(self).calls += 1
        raise AssertionError('test_fixture transport must never be invoked')


class TestFixtureRecordedExtractor:
    """Return explicitly marked synthetic facts through the recording boundary."""
    def __init__(self, store, config, *, mode, callback, budget_usd, recorder):
        self.store, self.config = store, config

    def key(self, document):
        return RecordingStore.key('extract', document, self.config)

    async def extract_with_response(self, document):
        block = next(block for block in document.blocks if block.text.strip())
        quote = block.text.strip().splitlines()[0]
        value = 'F-1' if 'F-1' in quote else 'fixture'
        facts = DocumentFacts(document.source_sha256, self.config.extractor_version, {
            'document_number': [Fact(value, Evidence(document.path, block.source_field or block.id,
                                                     block.page, quote))]})
        return ExtractionArtifact(facts, {'test_fixture': True},
            {'transformation_sha256': document.transformation_sha256}, (),
            {'cache_hit': False, 'test_fixture': True})


class DocumentSampleCaptureTests(unittest.TestCase):
    def _case_files(self, root, relative, source_bytes):
        phase = root / 'phase_dev'
        source = phase / relative
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(source_bytes)
        message_relative = 'inbox/messages/synthetic.txt'
        message = phase / message_relative
        message.parent.mkdir(parents=True, exist_ok=True)
        message.write_text('Synthetic test_fixture message')
        attachment = {'path': 'phase_dev/' + relative, 'sha256': digest(source_bytes)}
        manifest = root / 'manifest.json'
        manifest.write_text(json.dumps({'phase': 'phase_dev', 'cases': [{
            'case_id': 'SYNTHETIC-01', 'split': 'tuning', 'attachments': [attachment],
            'message': {'path': 'phase_dev/' + message_relative, 'sha256': digest(message.read_bytes())}}]}))
        return attachment, manifest

    def _capture_fixture_pdf(self, text, *, with_image=False, require_coverage=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve() / 'participant'
        root.mkdir()
        relative = 'inbox/ap/synthetic/invoice.pdf'
        source_bytes = b'SYNTHETIC TEST FIXTURE PDF PLACEHOLDER'
        attachment, manifest = self._case_files(root, relative, source_bytes)
        images = (PageImage(1, 'image/png', b'test-fixture-pixels'),) if with_image else ()
        prepared = ParsedDocument('inbox/ap/synthetic/invoice.pdf', attachment['sha256'],
            'application/pdf', 'test-fixture-router', (ParsedBlock('page.1', text, 1),), images=images)
        output = Path(temporary.name).resolve() / 'captures'
        args = fixture_args(root, output, manifest,
            require_native_row_coverage=require_coverage)
        with patch.object(capture_document_sample, 'AsyncLLMClient', TestFixtureTransport), \
             patch.object(capture_document_sample, 'RecordedExtractor', TestFixtureRecordedExtractor), \
             patch.object(capture_document_sample.DocumentRouter, 'parse', lambda _router, _path: prepared):
            code = asyncio.run(capture_document_sample.capture(args))
        status = json.loads((output / 'SYNTHETIC-01' / 'capture.json').read_text())
        return code, output, attachment, status

    def test_capture_xml_uses_source_tools_with_zero_provider_calls_and_is_eligible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / 'participant'
            root.mkdir()
            xml = (b'<Comprobante Version="4.0" Folio="F-1" Fecha="2026-07-01" Moneda="EUR" Total="12.00">'
                   b'<Emisor Rfc="AAA010101AAA" Nombre="Proveedor"/>'
                   b'<Receptor Rfc="BBB010101BBB" Nombre="Empresa"/></Comprobante>')
            attachment, manifest = self._case_files(root, 'inbox/ap/synthetic/invoice.xml', xml)
            output = Path(temporary).resolve() / 'captures'
            args = fixture_args(root, output, manifest)
            TestFixtureTransport.calls = 0
            with patch.object(capture_document_sample, 'AsyncLLMClient', TestFixtureTransport):
                self.assertEqual(asyncio.run(capture_document_sample.capture(args)), 0)
            status = json.loads((output / 'SYNTHETIC-01' / 'capture.json').read_text())
            self.assertFalse(status['new_capture'])
            self.assertTrue(status['live_evaluation_eligible'])
            attachment_status = status['attachments'][0]
            self.assertEqual(attachment_status['processing_kind'], 'source_tools')
            self.assertTrue(attachment_status['source_tools']['fresh_processing'])
            artifact = json.loads((output / 'SYNTHETIC-01' / 'artifacts' /
                                   (attachment['sha256'] + '.json')).read_text())
            self.assertIsNone(artifact['raw_response'])
            reports = list((output / 'SYNTHETIC-01' / 'reports').glob('*.json'))
            report = json.loads(reports[0].read_text())
            self.assertEqual(report['calls'], [])
            self.assertEqual(json.loads((output / 'SYNTHETIC-01' / 'config.json').read_text())['llm']['max_attempts'], 2)
            self.assertEqual(TestFixtureTransport.calls, 0)

    def test_capture_native_table_uses_outside_scope_and_preserves_raw_facts(self):
        row = f"{'Bolt':<45}{'2':>10} {'ud':<4}{'1,00':>12} {'2,00':>12}"
        text = 'Factura F-1\nDescripción                         Cant.  Ud.  Precio   Importe\n' + row + '\nBase imponible 2,00'
        code, output, attachment, status = self._capture_fixture_pdf(text)
        self.assertEqual(code, 0)
        self.assertEqual(status['status'], 'completed')
        item = status['attachments'][0]
        scope = item['extraction_config']['parameters']['prompt_extras']['extraction_scope']
        self.assertEqual(scope, 'outside_native_invoice_table')
        raw = json.loads((output / 'SYNTHETIC-01' / 'artifacts' / (attachment['sha256'] + '.json')).read_text())
        self.assertTrue(raw['provenance']['test_fixture'])
        self.assertFalse(any(name.startswith('line.') for name in raw['facts']['fields']))
        composition = json.loads((output / 'SYNTHETIC-01' / 'compositions' / (attachment['sha256'] + '.json')).read_text())
        self.assertEqual(composition['facts']['fields']['line.1.amount'][0]['value'], '2,00')
        self.assertEqual(composition['provenance']['composed_invoice_rows_origin'], 'deterministic_native_source')

    def test_capture_scan_uses_complete_scope_and_accepts_not_applicable_coverage(self):
        code, _, _, status = self._capture_fixture_pdf('Scanned invoice page', with_image=True,
                                                       require_coverage=True)
        self.assertEqual(code, 0)
        item = status['attachments'][0]
        self.assertEqual(item['extraction_config']['parameters']['prompt_extras'].get('extraction_scope'), None)
        self.assertEqual(item['native_row_coverage']['status'], 'not_applicable')
        self.assertEqual(status['status'], 'completed')

    def test_composition_archive_is_recomputed_from_original_raw_facts(self):
        row = f"{'Bolt':<45}{'2':>10} {'ud':<4}{'1,00':>12} {'2,00':>12}"
        text = ('Factura 1\nDescripción                         Cant.  Ud.  Precio   Importe\n'
                + row + '\nBase imponible 2,00')
        source_bytes = text.encode()
        original = ParsedDocument('inbox/ap/demo/invoice.pdf', digest(source_bytes), 'application/pdf',
                                  'test-parser', (ParsedBlock('page.1', text, 1),))
        raw = DocumentFacts(original.source_sha256, 'model-v1', {
            'document_number': [Fact('1', Evidence(original.path, 'page.1', 1, 'Invoice 1'))]})
        composition = compose_native_invoice(original, raw)
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'CASE'
            archive = directory / 'compositions' / (original.source_sha256 + '.json')
            archive.parent.mkdir(parents=True)
            payload = {'facts': composition.facts.to_dict(), 'provenance': composition.provenance,
                       'raw_model_facts_sha256': composition.provenance['recorded_model_facts_sha256']}
            archive.write_text(json.dumps(payload))
            item = {'composition_sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
            entry = {'sha256': original.source_sha256}
            self.assertEqual(composed_facts(directory, item, entry, original, raw).to_dict(),
                             composition.facts.to_dict())
            payload['facts']['fields']['line.1.amount'][0]['value'] = '999'
            archive.write_text(json.dumps(payload))
            item['composition_sha256'] = hashlib.sha256(archive.read_bytes()).hexdigest()
            with self.assertRaisesRegex(ValueError, 'does not recompute'):
                composed_facts(directory, item, entry, original, raw)

    def test_renderer_only_provenance_does_not_require_ocr_binary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / 'phase_dev' / 'inbox' / 'ap' / 'demo' / 'scan.pdf'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'original-pdf')
            source_hash = digest(source.read_bytes())
            document = ParsedDocument('inbox/ap/demo/scan.pdf', source_hash, 'application/pdf', 'test-parser',
                (ParsedBlock('page.1', 'Visible page', 1),),
                images=(PageImage(1, 'image/png', b'png-bytes'),),
                processing_aids=(ProcessingAid(1, '', {'kind': 'page_render', 'authoritative': False,
                    'source_sha256': source_hash, 'source_path': 'inbox/ap/demo/scan.pdf', 'page': 1,
                    'tools': {'renderer': {'version': 'pdftoppm 1', 'binary_sha256': 'a' * 64}},
                    'config': {'ocr_enabled': False}, 'image_sha256': digest(b'png-bytes'), 'text_sha256': digest(b''),
                }),))
            case_dir = root / 'capture' / 'CASE'
            archive = case_dir / 'sources' / (source_hash + '.json')
            archive.parent.mkdir(parents=True)
            archive.write_text(json.dumps(document.to_dict(include_images=True)))
            item = {'parsed_document_sha256': hashlib.sha256(archive.read_bytes()).hexdigest(),
                    'transformation_sha256': document.transformation_sha256}
            entry = {'path': 'phase_dev/inbox/ap/demo/scan.pdf', 'sha256': source_hash}
            self.assertEqual(captured_document(case_dir, item, entry, {'request_metadata': {
                'transformation_sha256': document.transformation_sha256}}, None, root).source_sha256, source_hash)


if __name__ == '__main__':
    unittest.main()
