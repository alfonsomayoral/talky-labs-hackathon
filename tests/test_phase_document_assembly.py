import asyncio
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from kalmora.documents.router import DocumentRouter
from kalmora.documents.xml_extractor import XMLDocumentExtractor
from kalmora.facts import Fact, atomic_json

SPEC = importlib.util.spec_from_file_location('phase_document_assembly', Path(__file__).parents[1] / 'tools/assemble_phase_document_facts.py')
assembly = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(assembly)


class AssemblyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.phase = self.root / 'phase'
        source = self.phase / 'inbox/ap/a/invoice.xml'
        source.parent.mkdir(parents=True)
        source.write_text('<Comprobante Version="4.0" Folio="TEST-1" Moneda="MXN" TipoDeComprobante="I" Total="10.00"><AdditionalInformation/></Comprobante>')
        self.document = DocumentRouter(self.phase).parse('inbox/ap/a/invoice.xml')
        self.facts = asyncio.run(XMLDocumentExtractor().extract(self.document))
        self.capture_root = self.root / 'capture'
        self.write_capture(self.capture_root, self.facts)

    def write_capture(self, root, facts):
        transformation = self.document.transformation_sha256
        atomic_json(root / 'parsed' / self.document.source_sha256 / (transformation + '.json'), self.document.to_dict())
        atomic_json(root / 'configurations' / ('c' * 64) / 'facts' / (transformation + '.json'), {'raw': facts.to_dict()})
        atomic_json(root / 'runs/one/capture.json', {'phase': 'phase_test', 'config_sha256': 'c' * 64, 'documents': [
            {'path': self.document.path, 'sha256': self.document.source_sha256,
             'transformation_sha256': transformation, 'status': 'completed'}]})

    def test_source_capture_lineage_and_raw_normalized_outputs_without_provider(self):
        report = assembly.assemble(self.phase, [self.capture_root], self.root / 'output')
        self.assertEqual(report['summary']['statuses'], {'assembled': 1})
        self.assertFalse(report['official_score_computed'])
        self.assertEqual(report['new_provider_calls'], 0)
        row = report['documents'][0]
        output = json.loads(Path(row['facts_file']).read_text())
        self.assertEqual(output['raw'], self.facts.to_dict())
        self.assertEqual(output['lineage']['capture_sha256'], assembly.file_sha(output['lineage']['capture']))
        self.assertEqual(row['uncited_pages'], [])

    def test_changed_original_and_uncaptured_source_remain_failed_denominators(self):
        (self.phase / self.document.path).write_text('changed original')
        (self.phase / 'inbox/uncaptured.xml').write_text('<source/>')
        report = assembly.assemble(self.phase, [self.capture_root], self.root / 'output')
        self.assertEqual(report['summary']['statuses'], {'failed': 2})
        self.assertTrue(any('changed' in row['error'] for row in report['documents']))
        self.assertTrue(any('no successful' in row['error'] for row in report['documents']))

    def test_latest_capture_cannot_hide_ungrounded_values(self):
        field = 'document_number'
        if field not in self.facts.fields:
            field = 'invoice_number'
        fact = self.facts.fields[field][0]
        changed = replace(self.facts, fields={**self.facts.fields, field: [Fact('INVENTED', fact.evidence)]})
        later = self.root / 'later'
        self.write_capture(later, changed)
        report = assembly.assemble(self.phase, [self.capture_root, later], self.root / 'output')
        self.assertEqual(report['summary']['statuses'], {'failed': 1})
        self.assertIn('value is not in its quote', report['documents'][0]['error'])

    def test_same_bytes_with_different_path_cannot_reuse_prepared_snapshot(self):
        parsed_path = self.capture_root / 'parsed' / self.document.source_sha256 / (self.document.transformation_sha256 + '.json')
        snapshot = self.document.to_dict()
        snapshot['path'] = 'inbox/ap/other/invoice.xml'
        atomic_json(parsed_path, snapshot)
        report = assembly.assemble(self.phase, [self.capture_root], self.root / 'output')
        self.assertEqual(report['summary']['statuses'], {'failed': 1})
        self.assertIn('source/path/transformation', report['documents'][0]['error'])

    def test_same_transformation_in_another_config_does_not_ambiguate_selected_run(self):
        atomic_json(self.capture_root / 'configurations' / ('d' * 64) / 'facts'
                    / (self.document.transformation_sha256 + '.json'), {'raw': self.facts.to_dict()})
        report = assembly.assemble(self.phase, [self.capture_root], self.root / 'output')
        self.assertEqual(report['summary']['statuses'], {'assembled': 1})
        self.assertIn('c' * 64, report['documents'][0]['source_capture'])

    def test_phase_identity_cannot_silently_relabel_september_as_july(self):
        with self.assertRaisesRegex(ValueError, 'different phase'):
            assembly.assemble(self.phase, [self.capture_root], self.root / 'output', phase='phase_dev')
        report_path = self.capture_root / 'runs/one/capture.json'
        capture = json.loads(report_path.read_text())
        capture['phase'] = 'phase_dev'
        atomic_json(report_path, capture)
        report = assembly.assemble(self.phase, [self.capture_root], self.root / 'output', phase='phase_dev')
        self.assertEqual(report['phase'], 'phase_dev')
        self.assertEqual(report['summary']['statuses'], {'assembled': 1})


if __name__ == '__main__':
    unittest.main()
