"""Synthetic failures at the partial/complete recording boundary, no network."""
from decimal import Decimal
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from kalmora.documents.extractor import DocumentInterpretationError, LLMDocumentExtractor
from kalmora.documents.replay import RecordedExtractor, RecordingConfig, RecordingStore, ReplayError, validate_state_coverage
from kalmora.documents.staged import capture_stages
from kalmora.llm.client import AsyncLLMClient, LLMConfig
from kalmora.runlog import RunRecorder
from tests.test_document_extractor import FixtureProvider, document, observation, group


class FieldRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def client(self, payload, directory):
        provider = FixtureProvider(payload)
        recorder = RunRecorder(directory, ['synthetic-field-recovery'])
        recorder.__enter__()
        self.addCleanup(recorder.__exit__, None, None, None)
        config = LLMConfig('gpt-6-luna', Decimal('1'), Decimal('0.000001'),
                           Decimal('0.000002'), 'test fixture', max_attempts=1)
        return AsyncLLMClient(config, recorder, provider=provider), provider

    def boundary(self, extractor, directory):
        return RecordedExtractor(RecordingStore(directory + '/recordings'),
            RecordingConfig.from_adapter(extractor), mode='record',
            callback=extractor.extract_with_response, budget_usd=Decimal('1'))

    async def test_failed_field_keeps_independent_proofs_after_it_but_never_accepts_partial(self):
        payload = {'observations': [observation('gross', '121,00', 'Gross 121,00'),
            observation('line.1.quantity', '2', 'Bolt M12 2 unit'),
            observation('net', '100,00', 'Net 100,00')], 'unknowns': []}
        with tempfile.TemporaryDirectory() as directory:
            client, _ = self.client(payload, directory)
            extractor = LLMDocumentExtractor(client, extraction_scope='header_footer_only',
                required_header_fields=('gross', 'net'), preserve_partial_on_failure=True)
            boundary = self.boundary(extractor, directory)
            with self.assertRaises(ReplayError):
                await boundary.extract_with_response(document())
            failure = boundary.store._read(boundary.key(document()), 'extract', failure=True)
            partial = failure['request_metadata']['partial_extraction']
            self.assertFalse(partial['usable_as_complete_capture'])
            self.assertEqual({item['field'] for item in partial['observations']}, {'gross', 'net'})
            with self.assertRaises(ReplayError):
                RecordedExtractor(boundary.store, boundary.config, mode='replay').read(document())

    async def test_omitted_header_repair_is_source_only_and_does_not_merge_rejected_answers(self):
        first = {'observations': [observation('gross', '121,00', 'Gross 121,00')], 'unknowns': []}
        second = {'observations': [observation('document_number', 'F-1', 'Invoice F-1'),
                                   observation('gross', '121,00', 'Gross 121,00')], 'unknowns': []}
        with tempfile.TemporaryDirectory() as directory:
            client, provider = self.client(first, directory)
            original = provider.invoke
            async def sequence(request):
                provider.payload = first if not provider.requests else second
                return await original(request)
            provider.invoke = sequence
            extractor = LLMDocumentExtractor(client, extraction_scope='header_footer_only',
                required_header_fields=('document_number', 'gross'), preserve_partial_on_failure=True,
                max_validation_attempts=2)
            boundary = self.boundary(extractor, directory)
            capture = await boundary.extract_with_response(document())
            self.assertEqual(len(provider.requests), 2)
            feedback = json.loads(provider.requests[1].prompt)['untrusted_validation_feedback']
            self.assertEqual(set(feedback[0]), {'category', 'detail'})
            self.assertEqual(capture.request_metadata['partial_extraction_attempts'][0]['status'], 'PARTIAL')
            self.assertEqual(capture.provenance['new_provider_calls'], 2)
            self.assertEqual(len(capture.facts.fields['gross']), 1)
            replay = RecordedExtractor(boundary.store, boundary.config, mode='replay').read(document())
            self.assertEqual(capture.facts, replay.facts)
            validate_state_coverage(boundary.config, replay.facts, replay.unknowns)

    async def test_two_stages_replay_exactly_and_keep_numeric_and_description_proofs_separate(self):
        headers = {'observations': [observation('document_number', 'F-1', 'Invoice F-1')], 'unknowns': []}
        rows = {'observations': [observation('line.1.description', 'Bolt M12', 'Bolt M12')],
                'groups': [group([('line.1.quantity', '2'), ('line.1.unit_price', '50,00'),
                                  ('line.1.amount', '100,00')], '2 unit 50,00 100,00')], 'unknowns': []}
        with tempfile.TemporaryDirectory() as directory:
            client, provider = self.client(headers, directory)
            original = provider.invoke
            async def choose(request):
                provider.payload = headers if json.loads(request.prompt)['extraction_scope'] == 'header_footer_only' else rows
                return await original(request)
            provider.invoke = choose
            head = self.boundary(LLMDocumentExtractor(client, extraction_scope='header_footer_only',
                required_header_fields=('document_number',), preserve_partial_on_failure=True), directory)
            table = self.boundary(LLMDocumentExtractor(client, extraction_scope='tables_only',
                require_line_descriptions=True, preserve_partial_on_failure=True), directory)
            live = await capture_stages(document(), head, table)
            replay = await capture_stages(document(),
                RecordedExtractor(head.store, head.config, mode='replay'),
                RecordedExtractor(table.store, table.config, mode='replay'))
            self.assertEqual(live.facts, replay.facts)
            self.assertEqual(len(provider.requests), 2)
            self.assertEqual(live.provenance['accounting_eligibility'], 'not_evaluated')
            self.assertNotEqual(live.facts.fields['line.1.amount'][0].evidence.quote,
                                live.facts.fields['line.1.description'][0].evidence.quote)
            self.assertEqual(live.facts.fields['line_count'][0].value, 1)
            from tools.evaluate_document_sample import staged_capture
            item = {'extraction_stages': [{'config': boundary.config.to_dict(), 'key': boundary.key(document())}
                                          for boundary in (head, table)]}
            verified = staged_capture(Path(directory), item, document(), live.to_dict())
            self.assertEqual(verified.facts, live.facts)
            altered = deepcopy(live.to_dict())
            altered['unknowns'] = [{'field': 'gross', 'status': 'MISSING', 'reason': 'hand edited'}]
            with self.assertRaises(ValueError):
                staged_capture(Path(directory), item, document(), altered)

    async def test_failed_table_preserves_accepted_header_but_cannot_complete_document(self):
        headers = {'observations': [observation('document_number', 'F-1', 'Invoice F-1')], 'unknowns': []}
        rows = {'observations': [observation('line.1.quantity', '2', '2 unit')], 'unknowns': []}
        with tempfile.TemporaryDirectory() as directory:
            client, provider = self.client(headers, directory)
            original = provider.invoke
            async def choose(request):
                provider.payload = headers if json.loads(request.prompt)['extraction_scope'] == 'header_footer_only' else rows
                return await original(request)
            provider.invoke = choose
            head = self.boundary(LLMDocumentExtractor(client, extraction_scope='header_footer_only',
                required_header_fields=('document_number',)), directory)
            table = self.boundary(LLMDocumentExtractor(client, extraction_scope='tables_only',
                require_line_descriptions=True, preserve_partial_on_failure=True), directory)
            with self.assertRaises(ReplayError):
                await capture_stages(document(), head, table)
            self.assertEqual(RecordedExtractor(head.store, head.config, mode='replay').read(document()).facts.fields[
                'document_number'][0].value, 'F-1')
            with self.assertRaises(ReplayError):
                RecordedExtractor(table.store, table.config, mode='replay').read(document())

    async def test_missing_state_never_becomes_null_observation_or_complete_coverage(self):
        payload = {'observations': [observation('document_number', 'F-1', 'Invoice F-1')],
                   'unknowns': [{'field': 'gross', 'status': 'MISSING', 'reason': 'No printed total.'}]}
        with tempfile.TemporaryDirectory() as directory:
            client, _ = self.client(payload, directory)
            extractor = LLMDocumentExtractor(client, extraction_scope='header_footer_only',
                required_header_fields=('gross',))
            capture = await extractor.extract_with_response(document())
            self.assertNotIn('gross', capture.facts.fields)
            config = RecordingConfig.from_adapter(extractor)
            validate_state_coverage(config, capture.facts, capture.unknowns)
            with self.assertRaises(ValueError):
                validate_state_coverage(config, capture.facts, ())
