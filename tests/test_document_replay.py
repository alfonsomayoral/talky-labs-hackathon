"""Offline recording/replay acceptance, without optional model/provider libraries."""
import asyncio
from dataclasses import replace
from decimal import Decimal
import json
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest

from kalmora.documents.contracts import Candidate, PageImage, ParsedBlock, ParsedDocument, ResolutionRequest, ResolutionResult, digest
from kalmora.documents.replay import (ExtractionCapture, RecordedExtractor, RecordedResolver,
    RecordingConfig, RecordingStore, ReplayError, ResolutionCapture)
from kalmora.documents.runner import StageRunner
from kalmora.facts import DocumentFacts, Evidence, Fact


def config():
    return RecordingConfig('openai', 'gpt-6-luna', 'extract-v1', 'prompt-v1', digest(b'prompt'),
                           'schema-v1', digest(b'schema'), {'reasoning_effort': 'low'})


def document(name='D1'):
    return ParsedDocument(f'inbox/ap/{name}/invoice.pdf', digest(name.encode()), 'application/pdf',
                          'parser-v1', (ParsedBlock('p1', 'Invoice F-001 vendor ABC total 12.34 rate 0.923456789', 1),))


def capture(doc, *, cost='0.01'):
    facts = DocumentFacts(doc.source_sha256, 'extract-v1', {
        'document_number': [Fact('F-001', Evidence(doc.path, 'p1', 1, 'F-001'))],
        'rate': [Fact(Decimal('0.923456789'), Evidence(doc.path, 'p1', 1, '0.923456789'))]})
    return ExtractionCapture(facts, {'status': 'completed', 'api_key': 'sk-secret', 'text': 'Bearer token'},
                             {'capture_cost_usd': cost, 'attempt_metrics': [{'attempt': 1}]},
                             unknowns=({'field': 'recipient_tax_id', 'status': 'MISSING'},))


def request(doc):
    return ResolutionRequest(doc, (Candidate('V1', {'name': 'ABC'}), Candidate('V2', {'name': 'XYZ'})),
                             {'master_version': 'v1'})


def selection(req):
    result = ResolutionResult('SELECTED', ('V1',), ({'candidate_id': 'V1', 'candidate_attribute': 'name',
        'candidate_value': 'ABC', 'source_value': 'ABC', 'block_id': 'p1', 'quote': 'ABC',
        'image_page': None, 'image_sha256': None, 'source_sha256': req.document.source_sha256},), 'literal name')
    return ResolutionCapture(result, {'status': 'completed'}, {'capture_cost_usd': '0.02', 'attempt_metrics': [{}, {}]})


class ReplayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store, self.cfg, self.doc = RecordingStore(self.root/'records'), config(), document()

    async def test_record_and_replay_exactly_without_callback_or_key(self):
        calls = []
        async def call(doc): calls.append(doc.path); return capture(doc)
        real = RecordedExtractor(self.store, self.cfg, mode='record', callback=call, budget_usd=Decimal('1'))
        first = await real.extract_with_response(self.doc)
        replay = RecordedExtractor(self.store, self.cfg, mode='replay')
        second = await replay.extract_with_response(self.doc)
        self.assertEqual(first.facts.to_dict(), second.facts.to_dict())
        self.assertEqual(second.facts.fields['rate'][0].value, Decimal('0.923456789'))
        self.assertEqual(second.unknowns, first.unknowns)
        self.assertEqual(len(calls), 1)
        self.assertEqual(second.provenance['new_provider_calls'], 0)
        self.assertEqual(second.provenance['new_provider_cost_usd'], '0')
        self.assertEqual(second.provenance['historical_capture_cost_usd'], '0.01')
        self.assertEqual(second.raw_response['api_key'], '[redacted]')
        self.assertNotIn('token', second.raw_response['text'])
        for path in (self.root/'records').rglob('*.json'):
            self.assertNotIn('sk-secret', path.read_text())
        with self.assertRaises(ValueError): RecordedExtractor(self.store, self.cfg, mode='replay', callback=call)
        with self.assertRaises(ValueError): RecordedExtractor(self.store, self.cfg, mode='record', callback=call)

    async def test_keys_invalidate_source_parser_transform_model_prompt_schema_parameters(self):
        self.store.save('extract', self.doc, self.cfg, capture(self.doc))
        variants = [replace(self.doc, source_sha256=digest(b'new')), replace(self.doc, parser_version='v2'),
                    replace(self.doc, blocks=(ParsedBlock('p1', 'changed', 1),))]
        for changed in variants:
            with self.assertRaises(ReplayError) as error:
                await RecordedExtractor(self.store, self.cfg, mode='replay').extract(changed)
            self.assertEqual(error.exception.category, 'missing')
        for changed in [replace(self.cfg, model='other'), replace(self.cfg, prompt_sha256=digest(b'new prompt')),
                        replace(self.cfg, schema_sha256=digest(b'new schema')),
                        replace(self.cfg, parameters={'reasoning_effort': 'medium'})]:
            with self.assertRaises(ReplayError): await RecordedExtractor(self.store, changed, mode='replay').extract(self.doc)

    async def test_resolution_candidates_context_and_proof_are_verified(self):
        req = request(self.doc)
        self.store.save('resolve', req, self.cfg, selection(req))
        adapter = RecordedResolver(self.store, self.cfg, mode='replay')
        self.assertEqual((await adapter.resolve(req)).selected_ids, ('V1',))
        for changed in [replace(req, context={'master_version': 'v2'}),
                        replace(req, candidates=(Candidate('V1', {'name': 'CHANGED'}),))]:
            with self.assertRaises(ReplayError): await adapter.resolve(changed)
        key = adapter.key(req)
        envelope = self.store._read(key, 'resolve')
        envelope['accepted']['evidence'][0]['candidate_value'] = 'fabricated'
        self.store._write(key, envelope)
        with self.assertRaises(ReplayError): await adapter.resolve(req)

    async def test_checksum_and_accepted_value_tampering_fail_without_fallback(self):
        self.store.save('extract', self.doc, self.cfg, capture(self.doc))
        key = self.store.key('extract', self.doc, self.cfg)
        path = self.store._path(key)
        payload = json.loads(path.read_text())
        payload['sha256'] = '0'*64
        path.write_text(json.dumps(payload))
        calls = []
        async def call(doc): calls.append(doc); return capture(doc)
        adapter = RecordedExtractor(self.store, self.cfg, mode='record', callback=call, budget_usd=Decimal('1'))
        with self.assertRaises(ReplayError): await adapter.extract(self.doc)
        self.assertFalse(calls)
        self.store.save('extract', self.doc, self.cfg, capture(self.doc))
        envelope = self.store._read(key, 'extract')
        envelope['accepted']['fields']['document_number'][0]['value'] = 'INVENTED'
        self.store._write(key, envelope)
        with self.assertRaises(ReplayError): await RecordedExtractor(self.store, self.cfg, mode='replay').extract(self.doc)

    async def test_empty_xml_and_derived_count_are_narrow_exceptions(self):
        xml = replace(self.doc, media_type='application/xml', blocks=(ParsedBlock('x1', '', source_field='/Invoice/IBAN'),))
        facts = DocumentFacts(xml.source_sha256, 'extract-v1', {'iban': [Fact(None, Evidence(xml.path, '/Invoice/IBAN', quote=''))]})
        self.store.save('extract', xml, self.cfg, ExtractionCapture(facts, {}, {}), origin='synthetic')
        self.assertIsNone((await RecordedExtractor(self.store, self.cfg, mode='fixture').extract(xml)).fields['iban'][0].value)
        nonempty = replace(xml, blocks=(ParsedBlock('x1', 'ABC', source_field='/Invoice/IBAN'),))
        with self.assertRaises(ValueError): self.store.save('extract', nonempty, self.cfg, ExtractionCapture(facts, {}, {}))
        source = self.doc
        evidence = Evidence(source.path, 'p1', 1, 'ABC')
        lines = DocumentFacts(source.source_sha256, 'extract-v1', {'line.1.description': [Fact('ABC', evidence)],
                                                               'line_count': [Fact(1, evidence)]})
        provenance = {'derived_fields': {'line_count': {'method': 'count_unique_contiguous_line_ids',
                                                       'line_ids': [1], 'source_fields': ['p1']}}}
        self.store.save('extract', source, self.cfg, ExtractionCapture(lines, {}, {}, provenance), origin='synthetic')
        key = self.store.key('extract', source, self.cfg)
        envelope = self.store._read(key, 'extract')
        envelope['artifact_provenance']['derived_fields']['line_count']['line_ids'] = [1, 2]
        self.store._write(key, envelope)
        with self.assertRaises(ReplayError): await RecordedExtractor(self.store, self.cfg, mode='fixture').extract(source)

    async def test_image_hash_proof_preserved_but_quote_not_claimed_verified(self):
        image = PageImage(1, 'image/png', b'original image bytes')
        doc = replace(self.doc, blocks=(ParsedBlock('p1', '', 1),), images=(image,))
        facts = DocumentFacts(doc.source_sha256, 'extract-v1', {'document_number': [Fact('F-001', Evidence(doc.path, 'image:'+image.sha256, 1, 'F-001'))]})
        self.store.save('extract', doc, self.cfg, ExtractionCapture(facts, {}, {}, {'image_quote_review': ['manual review']}), origin='synthetic')
        playback = RecordedExtractor(self.store, self.cfg, mode='fixture')
        self.assertEqual((await playback.extract(doc)).fields['document_number'][0].value, 'F-001')
        key = playback.key(doc)
        envelope = self.store._read(key, 'extract')
        envelope['accepted']['fields']['document_number'][0]['evidence']['field'] = 'image:'+'0'*64
        self.store._write(key, envelope)
        with self.assertRaises(ReplayError): await playback.extract(doc)

    async def test_fixture_failures_and_ambiguity_are_not_accounting_decisions(self):
        for category in ['refusal', 'invalid_response', 'timeout', 'budget']:
            doc = document(category)
            self.store.save_failure('extract', doc, self.cfg, category, origin='synthetic')
            with self.assertRaises(ReplayError) as error:
                await RecordedExtractor(self.store, self.cfg, mode='fixture').extract(doc)
            self.assertEqual(error.exception.category, category)
            self.assertFalse(self.store._path(self.store.key('extract', doc, self.cfg)).exists())
        req = request(self.doc)
        ambiguous = ResolutionCapture(ResolutionResult('AMBIGUOUS', (), (), 'two plausible candidates'), {}, {})
        self.store.save('resolve', req, self.cfg, ambiguous, origin='synthetic')
        self.assertEqual((await RecordedResolver(self.store, self.cfg, mode='fixture').resolve(req)).status, 'AMBIGUOUS')
        with self.assertRaises(ReplayError): await RecordedResolver(self.store, self.cfg, mode='replay').resolve(req)

    async def test_failed_record_can_resume_without_caching_failure_as_facts(self):
        calls = []
        async def call(doc):
            calls.append(doc)
            if len(calls) == 1: raise TimeoutError()
            return capture(doc, cost=None)
        adapter = RecordedExtractor(self.store, self.cfg, mode='record', callback=call, budget_usd=Decimal('1'))
        with self.assertRaises(ReplayError): await adapter.extract(self.doc)
        self.assertFalse(self.store._path(adapter.key(self.doc)).exists())
        accepted = await adapter.extract_with_response(self.doc)
        self.assertEqual(len(calls), 2)
        self.assertIsNone(accepted.provenance['historical_capture_cost_usd'])
        replay = await RecordedExtractor(self.store, self.cfg, mode='replay').extract_with_response(self.doc)
        self.assertIsNone(replay.provenance['historical_capture_cost_usd'])
        self.assertEqual(replay.provenance['new_provider_cost_usd'], '0')

    def test_import_and_fixture_mode_never_load_optional_provider_or_network(self):
        code = '''
import sys, socket, importlib.abc, asyncio, tempfile
class Forbidden(importlib.abc.MetaPathFinder):
 def find_spec(self, fullname, path=None, target=None):
  if fullname.split('.')[0] in {'openai','pydantic','pydantic_ai','httpx'}:
   raise AssertionError('provider import '+fullname)
sys.meta_path.insert(0, Forbidden())
socket.socket.connect=lambda *a,**k: (_ for _ in ()).throw(AssertionError('network'))
socket.socket.connect_ex=socket.socket.connect
from kalmora.documents.replay import RecordingConfig, RecordingStore, RecordedExtractor
from kalmora.documents.runner import StageRunner
from kalmora.documents.contracts import digest, ParsedDocument
from kalmora.documents.replay import ExtractionCapture
from kalmora.facts import DocumentFacts
c=RecordingConfig('offline','synthetic','v1','p1',digest(b'p'),'s1',digest(b's'))
with tempfile.TemporaryDirectory() as tmp:
 store=RecordingStore(tmp)
 doc=ParsedDocument('inbox/ap/D/empty.pdf',digest(b'empty'),'application/pdf','v1',())
 facts=DocumentFacts(doc.source_sha256,'v1',{})
 store.save('extract',doc,c,ExtractionCapture(facts,{},{}),origin='synthetic')
 e=RecordedExtractor(store,c,mode='fixture')
 assert asyncio.run(e.extract(doc)).fields=={}
assert not any(x.split('.')[0] in {'openai','pydantic','pydantic_ai'} for x in sys.modules)
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                                env={'PYTHONPATH': str(Path(__file__).resolve().parents[1]/'src'), 'PATH': '/usr/bin:/bin'})
        self.assertEqual(result.returncode, 0, result.stderr)


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.store, self.cfg = RecordingStore(self.root/'records'), config()

    async def test_bounded_concurrency_deterministic_writes_and_resume(self):
        docs = [document('D3'), document('D1'), document('D2')]
        active = peak = 0
        calls = []
        async def callback(doc):
            nonlocal active, peak
            calls.append(doc.path); active += 1; peak = max(peak, active)
            await asyncio.sleep(0.02 if 'D3' in doc.path else 0.001)
            active -= 1
            return capture(doc)
        class Landing:
            def __init__(self): self.items = {}; self.order = []; self.owner = threading.get_ident()
            def store_facts(self, path, facts):
                assert threading.get_ident() == self.owner
                if path not in self.items: self.order.append(path)
                self.items[path] = facts.to_dict()
        landing = Landing()
        adapter = RecordedExtractor(self.store, self.cfg, mode='record', callback=callback, budget_usd=Decimal('1'))
        runner = StageRunner(self.root/'states', adapter, concurrency=2, landing=landing)
        first = await runner.run(docs, phase='phase_without_golden')
        self.assertEqual(peak, 2)
        self.assertEqual(landing.order, [doc.path for doc in docs])
        again = await runner.run(docs, phase='phase_without_golden')
        replay = StageRunner(self.root/'replay-states', RecordedExtractor(self.store, self.cfg, mode='replay'), landing=landing)
        played = await replay.run(docs, phase='phase_without_golden')
        self.assertEqual(first.stable_sha256, again.stable_sha256)
        self.assertEqual(first.stable_sha256, played.stable_sha256)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(landing.items), 3)
        self.assertEqual(played.report['new_provider_calls'], 0)
        self.assertEqual(played.report['new_provider_cost_usd'], '0')
        subset = await runner.run(docs, phase='phase_without_golden', selected_paths={docs[1].path},
                                 regenerate_paths={docs[1].path}, regenerate_stages={'extract'})
        self.assertEqual([run.path for run in subset.documents], [docs[1].path])
        self.assertEqual(len(calls), 4)

    async def test_selected_resolution_context_invalidates_and_does_not_reextract(self):
        doc = document()
        self.store.save('extract', doc, self.cfg, capture(doc), origin='synthetic')
        prepared = StageRunner.prepare_resolution(request(doc), capture(doc).facts, phase='phaseA', context={'prior_selection': 'V1'})
        self.store.save('resolve', prepared, self.cfg, selection(prepared), origin='synthetic')
        runner = StageRunner(self.root/'states', RecordedExtractor(self.store, self.cfg, mode='fixture'),
                             resolver=RecordedResolver(self.store, self.cfg, mode='fixture'))
        good = await runner.run([doc], phase='phaseA', stages=('resolve',), request_builder=lambda doc, facts: request(doc),
                                context={'prior_selection': 'V1'})
        self.assertEqual(good.documents[0].stages[0].status, 'ACCEPTED')
        changed = await runner.run([doc], phase='phaseA', stages=('resolve',), request_builder=lambda doc, facts: request(doc),
                                   context={'prior_selection': 'V2'})
        self.assertEqual(changed.documents[0].stages[0].error, 'missing')
        self.assertEqual(changed.report['new_provider_calls'], 0)
        self.assertNotEqual(good.documents[0].stages[0].key, changed.documents[0].stages[0].key)

    async def test_controlled_cancel_and_resume(self):
        doc = document()
        started = asyncio.Event()
        calls = 0
        async def callback(source):
            nonlocal calls
            calls += 1
            if calls == 1:
                started.set()
                await asyncio.sleep(10)
            return capture(source)
        adapter = RecordedExtractor(self.store, self.cfg, mode='record', callback=callback, budget_usd=Decimal('1'))
        runner = StageRunner(self.root/'states', adapter)
        task = asyncio.create_task(runner.run([doc], phase='phaseA'))
        await started.wait(); task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        states = [json.loads(path.read_text()) for path in (self.root/'states').glob('*.json')]
        self.assertTrue(any(state['status'] == 'CANCELLED' for state in states))
        resumed = await runner.run([doc], phase='phaseA')
        self.assertEqual(resumed.documents[0].stages[0].status, 'ACCEPTED')
        self.assertEqual(calls, 2)

    @unittest.skipUnless(importlib.util.find_spec('duckdb'), 'Install landing extra for actual writer integration')
    async def test_actual_landing_replay_resume_does_not_duplicate_facts(self):
        from kalmora.landing import LandingStore
        phase = self.root/'phase_custom'
        for area in ['erp', 'tasks', 'inbox/ap/D1']:
            (phase/area).mkdir(parents=True)
        (phase/'tasks/close.json').write_text('{"month":"2027-02","steps":[]}')
        (phase/'erp/companies.json').write_text('[]')
        (phase/'inbox/ap/D1/message.json').write_text('{"doc_id":"D1","attachments":["invoice.pdf"]}')
        payload = b'%PDF synthetic fixture original'
        (phase/'inbox/ap/D1/invoice.pdf').write_bytes(payload)
        doc = replace(document(), source_sha256=digest(payload))
        self.store.save('extract', doc, self.cfg, capture(doc), origin='synthetic')
        adapter = RecordedExtractor(self.store, self.cfg, mode='fixture')
        with LandingStore(self.root/'landing.duckdb') as landing:
            landing.import_phase(phase)
            runner = StageRunner(self.root/'states', adapter, landing=landing)
            first = await runner.run([doc], phase=phase.name)
            repeated = await runner.run([doc], phase=phase.name)
            self.assertEqual(first.stable_sha256, repeated.stable_sha256)
            self.assertEqual(landing.counts()['document'], 1)
            facts = DocumentFacts.from_dict(json.loads(landing.rows('document')[0]['facts_json']))
            self.assertEqual(facts.to_dict(), capture(doc).facts.to_dict())


if __name__ == '__main__': unittest.main()
