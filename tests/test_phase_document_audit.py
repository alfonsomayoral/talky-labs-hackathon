"""Original-source runner checks: no labels, provider, or accounting fixtures."""
import asyncio
import importlib.util
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from kalmora.documents.contracts import ParsedBlock, ParsedDocument
from kalmora.facts import DocumentFacts, Evidence, Fact

SPEC = importlib.util.spec_from_file_location('phase_document_audit', Path(__file__).parents[1] / 'tools/audit_phase_documents.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class ArchiveSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.archive = self.root / 'source.zip'
        self.destination = self.root / 'septiembre'

    def tearDown(self):
        self.temp.cleanup()

    def archive_files(self, extra=None):
        with zipfile.ZipFile(self.archive, 'w') as container:
            container.writestr('participant/phase_test/inbox/ap/new/message.json', '{}')
            container.writestr('participant/phase_test/tasks/ap_documents.json', '[]')
            container.writestr('participant/phase_test/erp/vendors.jsonl', '{}\n')
            container.writestr('participant/phase_test/golden/no-read.json', 'ignored')
            container.writestr('participant/phase_test/bank/no-read.csv', 'ignored')
            if extra:
                container.writestr(extra, 'unsafe')

    def test_allowlist_hashes_reuse_and_no_overwrite(self):
        self.archive_files()
        root, manifest = audit.extract_sources(self.archive, self.destination)
        self.assertEqual(len(manifest['files']), 3)
        self.assertFalse((root / 'golden').exists())
        self.assertFalse((root / 'bank').exists())
        self.assertEqual(manifest['archive_sha256'], audit.sha256(self.archive))
        self.assertEqual(audit.extract_sources(self.archive, self.destination), (root, manifest))
        original = root / 'inbox/ap/new/message.json'
        original.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'Existing source differs'):
            audit.extract_sources(self.archive, self.destination)
        self.assertEqual(original.read_text(), 'changed')

    def test_all_entries_validated_before_write_even_outside_allowlist(self):
        for name in ('../escaped', '/absolute', 'outside/../../escaped', 'participant/phase_test/inbox\\bad', 'C:/windows'):
            with self.subTest(name=name):
                self.archive_files(name)
                with self.assertRaises(ValueError):
                    audit.extract_sources(self.archive, self.destination)
                self.assertFalse(self.destination.exists())

    def test_symlink_entry_rejected(self):
        self.archive_files()
        with zipfile.ZipFile(self.archive, 'a') as container:
            item = zipfile.ZipInfo('participant/phase_test/inbox/link')
            item.external_attr = (stat.S_IFLNK | 0o777) << 16
            container.writestr(item, '/tmp/target')
        with self.assertRaises(ValueError):
            audit.extract_sources(self.archive, self.destination)
        self.assertFalse(self.destination.exists())

    def test_original_inventory_rejects_symlinks(self):
        (self.destination / 'inbox').mkdir(parents=True)
        (self.destination / 'inbox/link').symlink_to(self.archive)
        with self.assertRaises(ValueError):
            audit.original_files(self.destination)

    def test_page_coverage_keeps_uncited_page_visible(self):
        document = ParsedDocument('inbox/ap/new/source.pdf', 'a' * 64, 'application/pdf', 'test',
                                  (ParsedBlock('page.1', 'One', 1), ParsedBlock('page.2', 'Two', 2)))
        facts = DocumentFacts('a' * 64, 'test', {'title': [Fact('One', Evidence(document.path, 'page.1', 1, 'One'))]})
        coverage = audit.source_coverage(document, facts, [{'page': 1}, {'page': 2}])
        self.assertEqual([row['fact_citation_present'] for row in coverage], [True, False])
        self.assertTrue(all(not row['literal_fidelity_independently_verified'] for row in coverage))

    def test_inventory_is_offline_and_has_failure_denominator(self):
        (self.destination / 'inbox').mkdir(parents=True)
        (self.destination / 'inbox/broken.pdf').write_bytes(b'not a pdf')
        (self.destination / 'inbox/message.json').write_text('{}')
        manifest = audit.inventory(self.destination)
        self.assertEqual(manifest['summary']['sources'], 2)
        self.assertEqual(manifest['summary']['pdfs'], 1)
        self.assertEqual(manifest['summary']['parse_failures'], 1)
        self.assertFalse(manifest['evaluation_performed'])

    def test_xml_capture_has_no_provider_calls_and_serializes_diagnostics(self):
        (self.destination / 'inbox').mkdir(parents=True)
        (self.destination / 'inbox/invoice.xml').write_text(
            '<Comprobante Version="4.0" Folio="NEW" Moneda="MXN" TipoDeComprobante="I" Total="10.00"/>')
        run = self.root / 'output' / 'run'
        run.mkdir(parents=True)
        args = audit.argparse.Namespace(phase_root=self.destination, output=self.root / 'output',
            budget=audit.Decimal('1'), input_usd_per_million=audit.Decimal('.1'),
            output_usd_per_million=audit.Decimal('.5'), pricing_provenance='synthetic test rates',
            model='gpt-6-luna', reasoning_effort='low', concurrency=2, omit_ocr_aids=False,
            path=None, pdf_renderer=None, tesseract=None, tool_timeout_seconds=120, fresh=False, page_strips=False)
        with patch('kalmora.llm.client.AsyncLLMClient.complete', side_effect=AssertionError('Provider must not be called')):
            result = asyncio.run(audit.capture(args, audit.inventory(self.destination), run))
        self.assertEqual(result, 0)
        capture = json.loads((run / 'capture.json').read_text())
        self.assertEqual(capture['documents'][0]['origin'], 'deterministic_xml')
        report = json.loads(Path(capture['run_report']).read_text())
        self.assertEqual(report['calls'], [])
        self.assertEqual(report['cost']['status'], 'no_llm')
        self.assertFalse(capture['literal_fidelity_independently_verified'])


if __name__ == '__main__':
    unittest.main()
