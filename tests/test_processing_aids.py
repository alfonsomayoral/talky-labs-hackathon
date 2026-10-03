"""OCR can guide reading; it cannot establish source text or visual fidelity."""
from dataclasses import replace
from types import SimpleNamespace
import json
import unittest
from unittest.mock import patch

from kalmora.documents.contracts import (PageImage, ParsedBlock, ParsedDocument,
                                         ProcessingAid, digest)
from kalmora.documents.extractor import (DocumentInterpretationError,
                                         LLMDocumentExtractor, _ground)
from kalmora.documents.prompts import prompt_text
from kalmora.documents.replay import RecordingConfig, RecordingStore, validate_facts
from kalmora.facts import DocumentFacts, Evidence, Fact


def source():
    image = PageImage(1, 'image/png', b'synthetic-original-render-not-an-OCR-result')
    provenance = {'tool': 'tesseract', 'tool_version': '5.5.0', 'language': 'eng',
                  'language_data_sha256': digest(b'fixture-language-data'),
                  'renderer': 'pdftoppm', 'renderer_version': 'fixture',
                  'dpi': 300, 'psm': 4, 'word_confidence': 89.9,
                  'verification': 'UNVERIFIED_OCR', 'image_sha256': image.sha256}
    return ParsedDocument('inbox/ap/synthetic/scanned.pdf', digest(b'original-pdf'),
        'application/pdf', 'synthetic-parser', (ParsedBlock('page.1', '', 1),),
        (image,), processing_aids=(ProcessingAid(1, 'Unit price 77,19', provenance),))


def observation(*, block='page.1', page=None, image_hash=None):
    return SimpleNamespace(field='line.1.unit_price', value='77,19', kind='OBSERVED',
        block_id=block, quote='Unit price 77,19', image_page=page,
        image_sha256=image_hash)


def recorded_config():
    return RecordingConfig('synthetic', 'offline-fixture', 'fixture-v1', 'prompt-v1',
        digest(b'instructions'), 'schema-v1', digest(b'schema'), {'prompt_extras': {}})


class ProcessingAidContractTests(unittest.TestCase):
    def test_roundtrip_retains_unverified_provenance_without_creating_source_blocks(self):
        doc = source()
        payload = doc.to_dict()
        aid = payload['unverified_processing_aids'][0]
        self.assertEqual(aid['provenance']['verification'], 'UNVERIFIED_OCR')
        self.assertEqual(aid['provenance']['psm'], 4)
        self.assertEqual(aid['provenance']['dpi'], 300)
        restored = ParsedDocument.from_dict(json.loads(json.dumps(payload)))
        self.assertEqual(restored, doc)
        self.assertEqual(restored.blocks[0].text, '')
        self.assertEqual(len(restored.blocks), 1)
        self.assertNotIn('unverified_processing_aids', replace(doc, processing_aids=()).to_dict())
        self.assertIn('unverified_processing_aids', json.loads(prompt_text(doc, {}))['untrusted_document'])

    def test_aid_text_and_tool_config_invalidate_transformation_prompt_and_recording(self):
        doc = source()
        cfg = recorded_config()
        baseline = RecordingStore.key('extract', doc, cfg)
        changes = [replace(doc.processing_aids[0], text='Unit price 77,10')]
        for key, value in [('dpi', 400), ('psm', 6), ('language', 'spa'),
                           ('tool_version', 'different'), ('language_data_sha256', digest(b'other-data'))]:
            changes.append(replace(doc.processing_aids[0], provenance={**doc.processing_aids[0].provenance, key: value}))
        for aid in changes:
            changed = replace(doc, processing_aids=(aid,))
            with self.subTest(provenance=aid.provenance, text=aid.text):
                self.assertEqual(changed.source_sha256, doc.source_sha256)
                self.assertEqual(changed.blocks, doc.blocks)
                self.assertNotEqual(changed.transformation_sha256, doc.transformation_sha256)
                self.assertNotEqual(prompt_text(changed, {}), prompt_text(doc, {}))
                self.assertNotEqual(RecordingStore.key('extract', changed, cfg), baseline)

    def test_aid_requires_an_existing_original_page(self):
        doc = source()
        with self.assertRaises(ValueError):
            replace(doc, processing_aids=(replace(doc.processing_aids[0], page=2),))

    def test_exact_ocr_quote_does_not_ground_as_native_text_or_an_aid_block(self):
        doc = source()
        for block in ('page.1', 'ocr:page.1', 'unverified_processing_aids.0'):
            with self.subTest(block=block):
                item = observation(block=block)
                with self.assertRaises(DocumentInterpretationError):
                    _ground(doc, item.value, item)
                facts = DocumentFacts(doc.source_sha256, 'fixture-v1', {
                    'unit_price': [Fact(item.value, Evidence(doc.path, block, 1, item.quote))]})
                with self.assertRaises(ValueError):
                    validate_facts(doc, facts, 'fixture-v1')

    def test_real_image_identity_preserves_review_requirement_not_ocr_approval(self):
        doc = source()
        item = observation(page=1, image_hash=doc.images[0].sha256)
        evidence, review = _ground(doc, item.value, item)
        self.assertEqual(evidence.field, 'image:' + doc.images[0].sha256)
        self.assertEqual(review['image_sha256'], doc.images[0].sha256)
        self.assertEqual(review['quote'], item.quote)
        self.assertNotEqual(review.get('verification'), 'VERIFIED')
        self.assertFalse(review.get('verified', False))
        facts = DocumentFacts(doc.source_sha256, 'fixture-v1', {'unit_price': [Fact(item.value, evidence)]})
        validate_facts(doc, facts, 'fixture-v1', {'image_quote_review': [review]})
        # Replay checks citation identity, not whether the pixels really say77,19.
        # Its acceptance must never be described as a manual quote-fidelity review.

    def test_fake_image_hash_and_wrong_page_rejected_by_both_boundaries(self):
        doc = source()
        for page, image_hash in [(1, '0' * 64), (2, doc.images[0].sha256)]:
            with self.subTest(page=page, image_hash=image_hash):
                item = observation(page=page, image_hash=image_hash)
                with self.assertRaises(DocumentInterpretationError):
                    _ground(doc, item.value, item)
                facts = DocumentFacts(doc.source_sha256, 'fixture-v1', {
                    'unit_price': [Fact(item.value, Evidence(doc.path, 'image:' + image_hash, page, item.quote))]})
                with self.assertRaises(ValueError):
                    validate_facts(doc, facts, 'fixture-v1')


class ProcessingAidExtractorTests(unittest.IsolatedAsyncioTestCase):
    async def test_extraction_artifact_keeps_image_quote_review_and_aid_in_untrusted_prompt(self):
        doc = source()
        item = observation(page=1, image_hash=doc.images[0].sha256)
        requests = []

        async def complete(schema, instructions, prompt, *, images):
            requests.append((prompt, images))
            return SimpleNamespace(output=SimpleNamespace(observations=[item], unknowns=[]),
                                   request_metadata={}, raw_response={'status': 'completed'})

        class FixtureSchema:
            @staticmethod
            def model_json_schema():
                return {'title': 'offline fixture only'}

        extractor = LLMDocumentExtractor(SimpleNamespace(complete=complete))
        identity = {'provider': 'synthetic', 'model': 'offline-fixture', 'extractor_version': 'fixture-v1'}
        with patch('kalmora.documents.extractor.output_models', return_value=(FixtureSchema, None)), \
                patch.object(extractor, 'recording_identity', return_value=identity):
            artifact = await extractor.extract_with_response(doc)
        fact = artifact.facts.fields['line.1.unit_price'][0]
        self.assertEqual(fact.evidence.field, 'image:' + doc.images[0].sha256)
        self.assertEqual(len(artifact.provenance['image_quote_review']), 1)
        self.assertFalse(artifact.provenance['image_quote_review'][0].get('verified', False))
        self.assertEqual(json.loads(requests[0][0])['untrusted_document']['blocks'][0]['text'], '')
        self.assertEqual(json.loads(requests[0][0])['untrusted_document']['unverified_processing_aids'][0]['text'],
                         doc.processing_aids[0].text)
        self.assertEqual(len(requests[0][1]), 1)
        validate_facts(doc, artifact.facts, 'fixture-v1', artifact.provenance)


if __name__ == '__main__':
    unittest.main()
