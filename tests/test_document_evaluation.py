import copy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from kalmora.documents.evaluation import (FROZEN_THRESHOLDS, SourceAudit, _runtime,
    _semantic, _value_supported, canonical_field, evaluate_sample, normalize_value, validate_annotation_sources)
from kalmora.facts import DocumentFacts, Evidence, Fact
from kalmora.runlog import RunRecorder
from kalmora.documents.contracts import ParsedBlock, ParsedDocument, PageImage


class EvaluationTests(unittest.TestCase):
    def test_period_and_certificate_dates_require_actual_date_without_label_lookup(self):
        for field in ('period_start', 'period_end', 'service_period_start',
                      'service_period_end', 'contractor_certificate_valid_until',
                      'lines[0].period_end'):
            with self.subTest(field=field):
                self.assertEqual(normalize_value(field, '30/09/2026'), '2026-09-30')
                observed = {'field': field, 'value': '2026-09-30'}
                self.assertTrue(_value_supported(observed, 'hasta 30/09/2026', None))
                self.assertFalse(_value_supported(observed, 'desde dicha fecha', None))
                self.assertFalse(_value_supported(observed, 'hasta 29/09/2026', None))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = 'phase_dev/inbox/ap/example/original.txt'
        data = b'FACTURA INV-A dated 03/07/2026 total 1.234,50 EUR supplier TAX-A'
        p = self.root / self.path
        p.parent.mkdir(parents=True)
        p.write_bytes(data)
        self.sha = hashlib.sha256(data).hexdigest()
        attachment = {'path': self.path, 'sha256': self.sha, 'format': 'text'}
        self.manifest = {'selection_sha256': 'frozen', 'source_anchors': [],
            'cases': [{'case_id': 'T', 'doc_id': 'original', 'split': 'tuning',
                       'attachments': [attachment], 'message': attachment}],
            'evaluation_contract': {'thresholds': dict(FROZEN_THRESHOLDS),
                'candidate_model': 'gpt-6-luna', 'budget': {
                    'smoke_plus_sample_spend_cap_usd': '1.00', 'max_attempts_per_document': 2}}}
        def label(field, value, quote):
            return {'field': field, 'value': value, 'critical': True, 'state': 'present',
                'evidence': {'document': self.path, 'source_sha256': self.sha,
                    'field': 'text', 'quote': quote, 'page': None}}
        self.labels = [label('document_type', 'INVOICE', 'FACTURA'),
            label('invoice_number', 'INV-A', 'INV-A'),
            label('gross', '1234.50', '1.234,50 EUR'),
            label('document_date', '2026-07-03', '03/07/2026')]
        self.annotations = {'cases': [{'case_id': 'T', 'doc_id': 'original',
            'expected_document_type': self.labels[0], 'facts': self.labels[1:]}],
            'semantic_candidates': []}

    def capture(self):
        fields = {}
        for label in self.labels:
            field = {'invoice_number': 'document_number', 'document_type': 'document_type_hint'}.get(label['field'], label['field'])
            value = label['evidence']['quote'] if label['field'] in {'gross', 'document_date', 'document_type'} else label['value']
            fields[field] = [Fact(value, Evidence(self.path, 'text', quote=label['evidence']['quote']))]
        return {'T': DocumentFacts(self.sha, 'unit-fixture', fields).to_dict()}

    def report(self, captures=None, **kw):
        return evaluate_sample(self.manifest, self.annotations, captures or self.capture(),
            source_root=self.root, scope='tuning', **kw)

    def test_aliases_exact_numbers_dates_and_offline_never_live_pass(self):
        result = self.report()
        self.assertTrue(result['capture_correctness_passed'])
        self.assertFalse(result['passed'])
        self.assertEqual(result['metrics']['critical_exact']['denominator'], 4)
        self.assertEqual(result['per_format']['text']['denominator'], 4)
        self.assertTrue(result['per_field']['gross']['small_n'])
        self.assertEqual(canonical_field('lines.2.amount'), 'lines[2].amount')
        self.assertEqual(canonical_field('line.1.amount'), 'lines[1].amount')
        self.assertEqual(canonical_field('certification_current'), 'certified_current')
        self.assertEqual(normalize_value('gross', 123450, unit='integer_cents'), normalize_value('gross', '1.234,50 EUR'))
        with self.assertRaises(ValueError):
            normalize_value('gross', 1.2)

    def test_reviewed_absence_can_match_explicit_unknown_without_creating_null_fact(self):
        label = {'field': 'purchase_order_reference', 'state': 'absent', 'value': None,
            'evidence': {'document': self.path, 'source_sha256': self.sha, 'field': 'document.full',
                         'quote': None, 'verification': 'manual_text_and_render'}}
        self.annotations['cases'][0]['facts'].append(label)
        captured = self.capture()['T']
        state = {'field': 'po_reference', 'status': 'MISSING', 'reason': 'No order reference observed',
                 'document': self.path, 'source_sha256': self.sha}
        envelope = {'T': {'raw_facts': [captured], 'unknown_states': [state]}}
        result = self.report(envelope)
        self.assertTrue(result['capture_correctness_passed'])
        outcome = result['cases']['T']['fields'][-1]
        self.assertTrue(outcome['correct_missing_abstention'])
        self.assertFalse(outcome['present'])
        self.assertFalse(outcome['grounded'])
        self.assertEqual(result['metrics']['grounded_evidence']['denominator'], 4)
        self.assertEqual(result['cases']['T']['returned_values'], 4)
        for change in ({'source_sha256': '0' * 64}, {'status': 'AMBIGUOUS'}, {'reason': ''},
                       {'document': 'phase_dev/inbox/ap/another.txt'}):
            bad = {'T': {'raw_facts': [captured], 'unknown_states': [{**state, **change}]}}
            self.assertFalse(self.report(bad)['capture_correctness_passed'])
        self.assertFalse(self.report({'T': {'raw_facts': [captured]}})['capture_correctness_passed'])

    def test_unknown_for_present_value_does_not_count_as_correct_absence(self):
        captured = self.capture()['T']
        del captured['fields']['gross']
        envelope = {'T': {'raw_facts': [captured], 'unknown_states': [
            {'field': 'gross', 'status': 'MISSING', 'reason': 'Unable to read total',
             'document': self.path, 'source_sha256': self.sha}]}}
        self.assertFalse(self.report(envelope)['capture_correctness_passed'])

    def test_wrong_number_and_borrowed_quote_fail(self):
        captures = self.capture()
        captures['T']['fields']['gross'][0]['value'] = '1234.51'
        result = self.report(captures)
        self.assertFalse(result['capture_correctness_passed'])
        self.assertEqual(result['metrics']['critical_exact']['numerator'], 3)
        self.assertEqual(result['fabrication_audit']['unsupported_values_or_evidence'], 1)

    def test_missing_required_and_fake_evidence_fail(self):
        captures = self.capture()
        del captures['T']['fields']['document_number']
        captures['T']['fields']['gross'][0]['evidence']['quote'] = 'invented'
        result = self.report(captures)
        self.assertIn('case_completeness_gate', [x['code'] for x in result['violations']])
        self.assertFalse(result['capture_correctness_passed'])

    def test_correct_date_with_unrelated_real_quote_is_not_grounded(self):
        captures = self.capture()
        captures['T']['fields']['document_date'][0]['value'] = '2026-07-03'
        captures['T']['fields']['document_date'][0]['evidence']['quote'] = 'supplier TAX-A'
        self.assertFalse(self.report(captures)['capture_correctness_passed'])

    def test_hash_tamper_and_unknown_extra_fabrication(self):
        captures = self.capture()
        captures['T']['source_sha256'] = '0' * 64
        self.assertFalse(self.report(captures)['capture_correctness_passed'])
        captures = self.capture()
        captures['T']['fields']['extra'] = [{'value': 'invented', 'evidence': {'document': self.path, 'field': 'text', 'quote': 'supplier TAX-A', 'page': None}}]
        self.assertFalse(self.report(captures)['fabrication_audit']['zero_fabrication_established'])
        captures['T']['fields']['extra'][0]['value'] = 'TAX-A'
        self.assertTrue(self.report(captures)['capture_correctness_passed'])

    def test_thresholds_cannot_be_relaxed(self):
        self.manifest['evaluation_contract']['thresholds']['grounded_evidence_location_min'] = '0.5'
        self.assertIn('frozen_thresholds_changed', [x['code'] for x in self.report()['violations']])

    def test_only_declared_user_revision_removes_latency_gate_and_preserves_duration(self):
        contract = self.manifest['evaluation_contract']
        report = {'status': 'completed', 'elapsed_seconds': 120,
            'input_metadata': {'capture_mode': 'captured_live', 'transport_mode': 'default', 'response_source': 'provider_api'},
            'calls': [{'provider': 'openai', 'model': 'gpt-6-luna', 'input_tokens': 100, 'output_tokens': 20,
                'estimated_cost': '0.00014', 'pricing': {'currency': 'USD', 'unit': 'per_token',
                    'provenance': 'synthetic unit test rates', 'input_rate': '0.000001', 'output_rate': '0.000002'}}]}
        self.assertIn('latency_gate', [i['code'] for i in _runtime(['T'], {'T': report}, contract)[1]])
        contract['thresholds']['latency_p95_seconds_max'] = None
        self.assertIn('frozen_thresholds_changed', [i['code'] for i in self.report()['violations']])
        contract['threshold_revision'] = 'user-no-temporal-limit-2026-10-03'
        result = self.report()
        self.assertTrue(result['capture_correctness_passed'])
        self.assertIsNone(result['thresholds']['latency_p95_seconds_max'])
        self.assertEqual(result['threshold_revision'], contract['threshold_revision'])
        runtime, issues = _runtime(['T'], {'T': report}, contract)
        self.assertEqual(issues, [])
        self.assertEqual(runtime['p95_seconds'], 120)
        contract['thresholds']['critical_header_money_tax_line_amount_exact_min'] = '0.50'
        self.assertIn('frozen_thresholds_changed', [i['code'] for i in self.report()['violations']])

    def test_nineteen_of_twenty_correct_grounded_predictions_pass_coverage(self):
        captures = self.capture()
        for index in range(16):
            label = copy.deepcopy(self.labels[1])
            label.update(field=f'reference_{index}', value='TAX-A')
            label['evidence']['quote'] = 'supplier TAX-A'
            self.annotations['cases'][0]['facts'].append(label)
            captures['T']['fields'][label['field']] = [
                {'value': 'TAX-A', 'evidence': {'document': self.path, 'field': 'text',
                    'quote': 'supplier TAX-A', 'page': None}}]
        del captures['T']['fields']['reference_15']
        result = self.report(captures)
        self.assertTrue(result['capture_correctness_passed'])
        self.assertEqual(result['metrics']['critical_exact']['numerator'], 19)
        self.assertEqual(result['metrics']['critical_exact']['denominator'], 20)
        self.assertEqual(result['metrics']['grounded_evidence']['numerator'], 19)
        self.assertEqual(result['metrics']['grounded_evidence']['denominator'], 19)

    def test_normalized_units_and_dates_share_source_proof_without_double_count(self):
        raw = self.capture()['T']
        normalized = DocumentFacts(self.sha, 'normalized-fixture', {
            'gross_cents': [Fact(123450, Evidence(self.path, 'text', quote='1.234,50 EUR'))],
            'document_date': [Fact('2026-07-03', Evidence(self.path, 'text', quote='03/07/2026'))]})
        result = self.report({'T': {'raw_facts': [raw], 'normalized_facts': [normalized]}})
        self.assertTrue(result['capture_correctness_passed'])
        self.assertEqual(result['cases']['T']['returned_values'], 4)

    def test_synthetic_candidate_guards_are_separate(self):
        annotations = {'semantic_candidates': [
            {'case_id': 'synthetic-ambiguous', 'resolvability': 'ambiguous'},
            {'case_id': 'synthetic-wrong', 'resolvability': 'manually_unique', 'expected_candidate_id': 'A'}]}
        _, issues, fabricated = _semantic(annotations,
            {'synthetic-ambiguous': {'status': 'SELECTED', 'selected_ids': ['A']},
             'synthetic-wrong': {'selected_ids': ['INVENTED']}},
            {'synthetic-ambiguous': ['A', 'B'], 'synthetic-wrong': ['A', 'B']})
        self.assertEqual(fabricated, 1)
        self.assertIn('semantic_abstention_gate', [x['code'] for x in issues])
        self.assertIn('semantic_precision_gate', [x['code'] for x in issues])
        metrics, issues, _ = _semantic(annotations,
            {'synthetic-ambiguous': {'status': 'AMBIGUOUS', 'selected_ids': []},
             'synthetic-wrong': {'selected_ids': ['A']}},
            {'synthetic-ambiguous': ['A', 'B'], 'synthetic-wrong': ['A', 'B']})
        self.assertEqual(issues, [])
        self.assertEqual(metrics['abstention']['denominator'], 1)

    def test_cached_and_mock_run_cannot_claim_live_zero_cost(self):
        contract = self.manifest['evaluation_contract']
        _, issues = _runtime(['T'], {'T': {'status': 'completed', 'calls': [], 'elapsed_seconds': 0,
            'input_metadata': {'capture_mode': 'synthetic'}}}, contract)
        self.assertTrue(issues)
        report = {'status': 'completed', 'elapsed_seconds': 1,
            'input_metadata': {'capture_mode': 'captured_live', 'transport_mode': 'default', 'response_source': 'provider_api'},
            'calls': [{'provider': 'openai', 'model': 'gpt-6-luna', 'input_tokens': 100, 'output_tokens': 20,
                'estimated_cost': '0.00014', 'pricing': {'currency': 'USD', 'unit': 'per_token',
                    'provenance': 'synthetic unit test rates', 'input_rate': '0.000001', 'output_rate': '0.000002'}}]}
        runtime, issues = _runtime(['T'], {'T': report}, contract)
        self.assertEqual(issues, [])  # Arithmetic/provenance unit test, never a provider benchmark.
        self.assertEqual(runtime['total_estimated_usd'], '0.00014')
        free = copy.deepcopy(report)
        free['calls'][0]['estimated_cost'] = '0'
        free['calls'][0]['pricing'].update(input_rate='0', output_rate='0')
        self.assertTrue(_runtime(['T'], {'T': free}, contract)[1])
        report['input_metadata']['test_fixture'] = True
        self.assertTrue(_runtime(['T'], {'T': report}, contract)[1])
        report['calls'][0]['pricing'] = None
        self.assertTrue(_runtime(['T'], {'T': report}, contract)[1])

    def test_attempt_limit_is_per_operation_not_total_case_calls(self):
        call = {'provider': 'openai', 'model': 'gpt-6-luna', 'input_tokens': 100,
            'output_tokens': 20, 'estimated_cost': '0.00014',
            'pricing': {'currency': 'USD', 'unit': 'per_token', 'provenance': 'fixture rates',
                        'input_rate': '0.000001', 'output_rate': '0.000002'}}
        calls = []
        for prompt in ('attachment-a', 'attachment-b', 'semantic-request'):
            item = copy.deepcopy(call)
            item['usage'] = {'request': {'instructions_sha256': 'instructions',
                'prompt_sha256': prompt, 'output_schema_sha256': 'schema', 'images': []}}
            calls.append(item)
        report = {'status': 'completed', 'elapsed_seconds': 1, 'calls': calls,
            'input_metadata': {'capture_mode': 'captured_live', 'transport_mode': 'default',
                               'response_source': 'provider_api'}}
        contract = self.manifest['evaluation_contract']
        self.assertEqual(_runtime(['T'], {'T': report}, contract)[1], [])
        report['calls'] = [copy.deepcopy(calls[0]) for _ in range(3)]
        self.assertIn('attempt cap exceeded', str(_runtime(['T'], {'T': report}, contract)[1]))

    def test_source_boundary(self):
        audit = SourceAudit(self.root, self.manifest)
        for path in ['../outside', 'phase_test/inbox/a', 'golden/a']:
            with self.assertRaises(ValueError):
                audit.source(path)

    def test_image_hash_and_page_are_required_even_on_hybrid_page(self):
        audit = SourceAudit(self.root, self.manifest)
        image_hash = hashlib.sha256(b'synthetic-rendered-page').hexdigest()
        audit.content = lambda document: {'pages': ['native footer unrelated to invoice'],
                                         'images': {(1, image_hash)}}
        label = copy.deepcopy(self.labels[2])
        label['evidence'].update(page=1, verification='manual_image_transcription')
        prediction = {'field': 'gross', 'value': '1234.50', 'source_sha256': self.sha,
            'evidence': {'document': self.path, 'page': 1, 'field': 'image:' + image_hash,
                         'quote': '1.234,50 EUR'}}
        self.assertEqual(audit.proof(prediction, label)[0], 'grounded')
        self.assertEqual(audit.proof(prediction)[0], 'unreviewed')
        prediction['evidence']['quote'] = '1.234,50 EUR approved by an invented manager'
        self.assertEqual(audit.proof(prediction, label)[0], 'unreviewed')
        prediction['evidence']['quote'] = '1.234,50 EUR'
        prediction['evidence']['field'] = 'image:' + '0' * 64
        self.assertEqual(audit.proof(prediction, label)[0], 'unsupported')
        prediction['evidence']['field'] = 'image:' + image_hash
        prediction['evidence']['page'] = 2
        self.assertEqual(audit.proof(prediction, label)[0], 'unsupported')
        prediction['evidence'].update(page=1, field='text')
        self.assertEqual(audit.proof(prediction, label)[0], 'unsupported')

    def test_exact_manual_review_still_requires_real_image_and_literal_value(self):
        from kalmora.documents.image_reviews import image_review_identity, image_review_key
        image_hash = hashlib.sha256(b'original-image').hexdigest()
        transform = hashlib.sha256(b'original-transform').hexdigest()
        prediction = {'field': 'gross', 'value': '1234.50', 'source_sha256': self.sha,
            'evidence': {'document': self.path, 'page': 1, 'field': 'image:' + image_hash,
                         'quote': '1.234,50 EUR'}}
        key = image_review_key(prediction, transform)
        record = {'schema_version': 1, 'key': key, 'identity': image_review_identity(prediction, transform),
            'status': 'VERIFIED', 'review_basis': 'original_page_image', 'reviewer': 'synthetic reviewer',
            'date': '2026-10-03'}
        audit = SourceAudit(self.root, self.manifest, transformation_hashes={self.path: transform},
                            image_reviews={key: record})
        audit.content = lambda document: {'pages': [''], 'images': {(1, image_hash)}}
        self.assertEqual(audit.proof(prediction)[0], 'grounded')
        record['status'] = 'REJECTED'
        self.assertEqual(audit.proof(prediction)[0], 'unsupported')
        record['status'] = 'VERIFIED'
        audit.content = lambda document: {'pages': [''], 'images': {(1, '0' * 64)}}
        self.assertEqual(audit.proof(prediction)[0], 'unsupported')
        audit.content = lambda document: {'pages': [''], 'images': {(1, image_hash)}}
        prediction['evidence']['quote'] += ' unreviewed invented approval'
        self.assertEqual(audit.proof(prediction)[0], 'unreviewed')

    def test_fresh_validated_source_tools_zero_cost_is_distinct_from_cache(self):
        proof = {'adapter_name': 'xml_extractor', 'adapter_version': 'fixture-v1',
            'adapter_sha256': '1' * 64, 'config_sha256': '2' * 64,
            'source_sha256': self.sha, 'transformation_sha256': '3' * 64, 'fresh_processing': True}
        report = {'status': 'completed', 'elapsed_seconds': .01, 'calls': [], 'cache_hits': 0,
            'input_metadata': {'capture_mode': 'fresh_source_tools', 'transport_mode': 'local',
                'response_source': 'source_tools', 'source_tools_validated': True, 'source_tools': [proof]}}
        runtime, issues = _runtime(['T'], {'T': report}, self.manifest['evaluation_contract'])
        self.assertEqual(issues, [])
        self.assertEqual(runtime['total_estimated_usd'], '0')
        for mutation in ('cache', 'missing_hash', 'unvalidated', 'not_fresh'):
            bad = copy.deepcopy(report)
            if mutation == 'cache':
                bad['cache_hits'] = 1
            elif mutation == 'missing_hash':
                del bad['input_metadata']['source_tools'][0]['adapter_sha256']
            elif mutation == 'unvalidated':
                bad['input_metadata']['source_tools_validated'] = False
            else:
                bad['input_metadata']['source_tools'][0]['fresh_processing'] = False
            self.assertTrue(_runtime(['T'], {'T': bad}, self.manifest['evaluation_contract'])[1])

    def test_rendered_archive_images_replace_embedded_images_and_bind_transform(self):
        path = self.path.replace('.txt', '.pdf')
        (self.root / path).write_bytes(b'original synthetic PDF bytes')
        source_hash = hashlib.sha256((self.root / path).read_bytes()).hexdigest()
        manifest = copy.deepcopy(self.manifest)
        manifest['cases'][0]['attachments'][0].update(path=path, sha256=source_hash)
        parsed = ParsedDocument(path.removeprefix('phase_dev/'), source_hash, 'application/pdf',
            'test-renderer-v1', (ParsedBlock('page:1', 'native footer', 1),),
            (PageImage(1, 'image/png', b'rendered page'),))
        page = SimpleNamespace(extract_text=lambda **kw: 'native footer',
                               images=[SimpleNamespace(data=b'embedded original')])
        reader = SimpleNamespace(PdfReader=lambda stream: SimpleNamespace(pages=[page]))
        with patch.dict('sys.modules', {'pypdf': reader}):
            audit = SourceAudit(self.root, manifest, {path: parsed}, {path: parsed.transformation_sha256})
            self.assertEqual(audit.content(path)['images'], {(1, parsed.images[0].sha256)})
            invalid = SourceAudit(self.root, manifest, {path: parsed}, {path: '0' * 64})
            with self.assertRaisesRegex(ValueError, 'transformation mismatch'):
                invalid.content(path)

    def test_actual_runrecorder_scientific_prices_reproduce_cost(self):
        metadata = {'case_id': 'T', 'capture_mode': 'captured_live', 'transport_mode': 'default',
                    'response_source': 'provider_api'}
        with RunRecorder(self.root / 'reports', ['synthetic-test'], metadata) as recorder:
            recorder.record_call('openai', 'gpt-6-luna', 100, 20, {
                'currency': 'USD', 'unit': 'per_token', 'provenance': 'test-config',
                'input_rate': Decimal('1.25E-7'), 'output_rate': Decimal('5E-7')})
        runtime, issues = _runtime(['T'], {'T': recorder.report}, self.manifest['evaluation_contract'])
        self.assertEqual(issues, [])
        self.assertEqual(Decimal(runtime['total_estimated_usd']), Decimal('0.0000225'))
        recorder.report['calls'][0]['pricing']['input_rate'] = float('nan')
        self.assertTrue(_runtime(['T'], {'T': recorder.report}, self.manifest['evaluation_contract'])[1])

    def test_normalized_rate_ratio_is_grounded_in_percent_quote(self):
        source = b'FACTURA INV-A dated 03/07/2026 total 1.234,50 EUR supplier TAX-A IVA 21%'
        (self.root / self.path).write_bytes(source)
        self.sha = hashlib.sha256(source).hexdigest()
        case = self.manifest['cases'][0]
        case['attachments'][0]['sha256'] = case['message']['sha256'] = self.sha
        for label in self.labels:
            label['evidence']['source_sha256'] = self.sha
        captures = self.capture()
        captures['T']['fields']['tax_rate_e4'] = [{'value': 2100, 'evidence': {
            'document': self.path, 'field': 'text', 'quote': 'IVA 21%', 'page': None}}]
        self.assertTrue(self.report(captures)['capture_correctness_passed'])


class SealedOriginalTests(unittest.TestCase):
    def test_holdout_seal_and_original_anchors(self):
        root = os.environ.get('KALMORA_PARTICIPANT_ROOT')
        if not root:
            self.skipTest('Set KALMORA_PARTICIPANT_ROOT to verify external original documents')
        path = Path('fixtures/llm_eval/ap-holdout-annotations.json')
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), 'e471a50c39383d96681a891f7fb142696dfb60fb3d41408165720de266f0c866')
        annotations = json.loads(path.read_text())
        self.assertEqual(len(annotations['cases']), 8)
        self.assertEqual(sum(1 + len(c['facts']) for c in annotations['cases']), 199)
        self.assertEqual(validate_annotation_sources('docs/evaluation/ap-sample.json', path, root), [])


if __name__ == '__main__':
    unittest.main()
