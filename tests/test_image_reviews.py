"""Manual review binding tests use synthetic observations, never original answers."""
import copy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from kalmora.documents.image_reviews import (dump_registry, image_review_identity,
    image_review_key, load_registry, validate_review)


class ImageReviewTests(unittest.TestCase):
    def setUp(self):
        self.observed = {'field': 'lines[1].unit_price', 'value': '77,10', 'unit': None,
            'source_sha256': 'a' * 64, 'evidence': {'document': 'inbox/ap/synthetic/scan.pdf',
            'page': 1, 'field': 'image:' + 'b' * 64, 'quote': 'Unit price 77,10'}}
        self.transform = 'c' * 64

    def registry(self, status='VERIFIED'):
        key = image_review_key(self.observed, self.transform)
        return {key: {'schema_version': 1, 'key': key,
            'identity': image_review_identity(self.observed, self.transform), 'status': status,
            'review_basis': 'original_page_image', 'reviewer': 'synthetic human review fixture',
            'date': '2026-10-03'}}

    def test_exact_manual_review_and_relative_document_alias(self):
        registry = self.registry()
        self.assertEqual(validate_review(self.observed, self.transform, registry), 'VERIFIED')
        alias = copy.deepcopy(self.observed)
        alias['evidence']['document'] = './phase_dev/inbox/ap/synthetic/scan.pdf'
        self.assertEqual(image_review_key(alias, self.transform), image_review_key(self.observed, self.transform))
        self.assertEqual(validate_review(alias, self.transform, registry), 'VERIFIED')

    def test_wrong_ocr_value_or_high_confidence_cannot_approve(self):
        wrong = copy.deepcopy(self.observed)
        wrong['value'] = '77,19'
        wrong['evidence']['quote'] = 'Unit price 77,19'
        wrong['ocr_confidence'] = 99
        self.assertEqual(validate_review(wrong, self.transform, None), 'UNREVIEWED')
        self.assertEqual(validate_review(wrong, self.transform, self.registry()), 'UNREVIEWED')
        key = image_review_key(wrong, self.transform)
        fake = {'schema_version': 1, 'key': key, 'identity': image_review_identity(wrong, self.transform),
            'status': 'VERIFIED', 'review_basis': 'ocr_confidence', 'reviewer': 'OCR', 'date': '2026-10-03'}
        self.assertEqual(validate_review(wrong, self.transform, {key: fake}), 'UNREVIEWED')

    def test_every_observed_identity_component_is_bound(self):
        registry = self.registry()
        variants = []
        for name, value in [('source_sha256', 'd' * 64), ('field', 'lines[2].unit_price'),
                            ('value', '77,19'), ('unit', 'currency_major_decimal')]:
            changed = copy.deepcopy(self.observed); changed[name] = value; variants.append(changed)
        for name, value in [('page', 2), ('field', 'image:' + 'e' * 64),
                            ('quote', 'Unit price 77,10 invented'), ('quote', 'Unit  price 77,10'),
                            ('document', 'inbox/ap/synthetic/other.pdf')]:
            changed = copy.deepcopy(self.observed); changed['evidence'][name] = value; variants.append(changed)
        for changed in variants:
            with self.subTest(changed=changed):
                self.assertEqual(validate_review(changed, self.transform, registry), 'UNREVIEWED')
        self.assertEqual(validate_review(self.observed, 'f' * 64, registry), 'UNREVIEWED')

    def test_rejected_unreviewed_and_invalid_schema_do_not_verify(self):
        for status in ['REJECTED', 'UNREVIEWED']:
            self.assertEqual(validate_review(self.observed, self.transform, self.registry(status)), status)
        key = image_review_key(self.observed, self.transform)
        for changes in [{'status': 'APPROVED'}, {'reviewer': ''}, {'date': ' '},
                        {'review_basis': 'model_judge'}, {'key': '0' * 64},
                        {'confidence': 100}, {'schema_version': True}]:
            registry = self.registry(); registry[key].update(changes)
            self.assertEqual(validate_review(self.observed, self.transform, registry), 'UNREVIEWED')
        registry = self.registry()
        registry[key]['identity']['quote'] = 'Different quote'
        self.assertEqual(validate_review(self.observed, self.transform, registry), 'UNREVIEWED')

    def test_exact_typed_decimal_and_tag_collision_roundtrip(self):
        self.observed['value'] = {'amount': Decimal('1.234500'), 'source_tag': {'type': 'decimal', 'value': 'literal text'}}
        registry = self.registry()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'reviews.json'
            dump_registry(path, registry)
            loaded = load_registry(path)
            self.assertEqual(loaded, registry)
            self.assertEqual(validate_review(self.observed, self.transform, loaded), 'VERIFIED')
            self.assertIn('1.234500', path.read_text())
        changed = copy.deepcopy(self.observed)
        changed['value']['amount'] = Decimal('1.2345')
        self.assertNotEqual(image_review_key(changed, self.transform), image_review_key(self.observed, self.transform))
        self.assertEqual(validate_review(changed, self.transform, registry), 'UNREVIEWED')

    def test_invalid_identity_paths_and_image_locators_fail_closed(self):
        for name, value in [('document', '/absolute.pdf'), ('document', '../other.pdf'),
                            ('document', 'phase_test/inbox/x.pdf'), ('document', 'golden/x.pdf'),
                            ('field', 'image:' + 'b' * 64 + ':page1'), ('field', 'ocr:page.1'),
                            ('page', True), ('quote', '')]:
            changed = copy.deepcopy(self.observed); changed['evidence'][name] = value
            with self.subTest(name=name, value=value):
                with self.assertRaises(ValueError):
                    image_review_key(changed, self.transform)
                self.assertEqual(validate_review(changed, self.transform, self.registry()), 'UNREVIEWED')

    def test_registry_loader_rejects_untyped_and_unknown_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'reviews.json'
            path.write_text(json.dumps(self.registry()))
            with self.assertRaises(ValueError):
                load_registry(path)


if __name__ == '__main__':
    unittest.main()
