from dataclasses import replace
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import os
import shutil
from kalmora.documents.contracts import ParsedDocument, ParsedBlock, digest
from kalmora.documents.ocr import PDFVisionConfig, PDFVisionError, PDFVisionProcessor
try:
    from pypdf import PdfWriter
except ImportError:
    PdfWriter = None

@unittest.skipIf(PdfWriter is None, 'requires documents extra')
class PDFVisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'phase'
        self.source = self.root / 'inbox/ap/synthetic.pdf'
        self.source.parent.mkdir(parents=True)
        writer = PdfWriter(); writer.add_blank_page(width=612, height=792)
        writer.write(self.source)
        self.document = ParsedDocument('inbox/ap/synthetic.pdf', digest(self.source.read_bytes()),
            'application/pdf', 'synthetic-v1', (ParsedBlock('page.1', '', 1),), warnings=('page.1:vision_required',))

    def error(self, category, config=None, document=None, artifact_dir=None):
        with self.assertRaises(PDFVisionError) as caught:
            PDFVisionProcessor(self.root, config).process(document or self.document, artifact_dir)
        self.assertEqual(caught.exception.category, category)

    def test_source_hash_escape_and_artifact_original_guards(self):
        self.error('source_hash', document=replace(self.document, source_sha256='0'*64))
        outside = Path(self.temp.name) / 'outside.pdf'; outside.write_bytes(self.source.read_bytes())
        self.source.unlink(); self.source.symlink_to(outside)
        self.error('source_path')
        self.source.unlink(); self.source.write_bytes(outside.read_bytes())
        self.error('artifact_path', artifact_dir=self.root / 'output')

    def test_caps_precede_renderer_and_tools_missing_are_explicit(self):
        self.error('source_limit', replace(PDFVisionConfig(), max_source_bytes=10))
        self.error('pixel_limit', replace(PDFVisionConfig(), max_pixels_per_page=100))
        writer = PdfWriter(); writer.add_blank_page(612, 792); writer.add_blank_page(612, 792); writer.write(self.source)
        document = replace(self.document, source_sha256=digest(self.source.read_bytes()))
        self.error('page_limit', replace(PDFVisionConfig(), max_pages=1), document)
        self.error('missing_tool', replace(PDFVisionConfig(), renderer='/nonexistent/pdftoppm'), document)

    def test_portable_fallback_missing_tools_and_invalid_timeout(self):
        with patch('kalmora.documents.ocr.shutil.which', return_value=None):
            config = PDFVisionConfig()
            self.assertEqual(config.renderer, 'pdftoppm')
            self.assertEqual(config.tesseract, 'tesseract')
        self.error('missing_tool', replace(config, renderer='missing-renderer-binary'))
        for value in (True, '30', None, float('nan')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                PDFVisionConfig(timeout_seconds=value)
        # Native text requires no installed renderer or OCR tool.
        native = replace(self.document, warnings=(), blocks=(ParsedBlock('page.1', 'Original text', 1),))
        self.assertIs(PDFVisionProcessor(self.root, replace(config, renderer='missing-renderer-binary')).process(native), native)

    def test_subprocess_timeout_and_output_limits(self):
        processor = PDFVisionProcessor(self.root, replace(PDFVisionConfig(), timeout_seconds=.04))
        with self.assertRaises(PDFVisionError) as caught:
            processor._run([sys.executable, '-c', 'import time; time.sleep(1)'], self.root)
        self.assertEqual(caught.exception.category, 'timeout')
        processor = PDFVisionProcessor(self.root, replace(PDFVisionConfig(), max_ocr_bytes=100))
        with self.assertRaises(PDFVisionError) as caught:
            processor._run([sys.executable, '-c', 'print("x"*1000)'], self.root)
        self.assertEqual(caught.exception.category, 'output_limit')

    def test_multiple_page_resource_budget_and_invalid_page_locator(self):
        writer = PdfWriter()
        for _ in range(5):
            writer.add_blank_page(612, 792)
        writer.write(self.source)
        document = replace(self.document, source_sha256=digest(self.source.read_bytes()),
            blocks=tuple(ParsedBlock(f'page.{number}', '', number) for number in range(1, 6)),
            warnings=tuple(f'page.{number}:vision_required' for number in range(1, 6)))
        # Five pages are allowed now; a cumulative pixel budget still runs
        # before any renderer or OCR process is started.
        self.error('total_pixel_limit', replace(PDFVisionConfig(), max_total_pixels=12_000_000), document)
        self.error('page_locator', document=replace(document, warnings=('page.6:vision_required',)))
        self.error('page_locator', document=replace(document, blocks=(ParsedBlock('page.1', '', 1),)))
        for settings in ({'force_render_all_pages': 1}, {'ocr_enabled': None}, {'psm': 2}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                PDFVisionConfig(**settings)

    def test_render_only_audit_includes_every_page_without_ocr_tools(self):
        config = PDFVisionConfig(force_render_all_pages=True, ocr_enabled=False,
                                 tesseract='/nonexistent/tesseract')
        if not Path(shutil.which(config.renderer) or config.renderer).is_file():
            self.skipTest('local renderer not installed')
        writer = PdfWriter()
        for _ in range(5):
            writer.add_blank_page(72, 72)
        writer.write(self.source)
        document = replace(self.document, source_sha256=digest(self.source.read_bytes()), warnings=(),
            blocks=tuple(ParsedBlock(f'page.{number}', f'Native text I{number}', number) for number in range(1, 6)))
        processed = PDFVisionProcessor(self.root, config).process(document, Path(self.temp.name) / 'renders')
        self.assertEqual(processed.blocks, document.blocks)
        self.assertEqual(processed.source_sha256, document.source_sha256)
        self.assertEqual([image.page for image in processed.images], list(range(1, 6)))
        self.assertEqual([aid.provenance['kind'] for aid in processed.processing_aids], ['page_render'] * 5)
        self.assertTrue(all(aid.text == '' for aid in processed.processing_aids))
        for image, aid in zip(processed.images, processed.processing_aids):
            self.assertEqual(aid.provenance['image_sha256'], image.sha256)
            self.assertEqual(aid.provenance['render_scope'], 'full_media_box')
            self.assertNotIn('ocr', aid.provenance['tools'])
        self.error('already_processed', config, processed)

    def test_real_synthetic_scan_has_unverified_provenance_and_preserved_blocks(self):
        config = PDFVisionConfig(renderer=os.environ.get('KALMORA_TEST_PDFTOPPM'), tesseract=os.environ.get('KALMORA_TEST_TESSERACT'))
        if not Path(shutil.which(config.renderer) or config.renderer).is_file() or not Path(config.tesseract).is_file():
            self.skipTest('local renderer/OCR not installed')
        try:
            from PIL import Image, ImageDraw, ImageFont
        except ImportError:
            self.skipTest('Pillow unavailable for synthetic scan creation')
        image = Image.new('RGB', (1500, 500), 'white')
        ImageDraw.Draw(image).text((60, 150), 'SYNTHETIC INVOICE TOTAL 123.45', fill='black', font=ImageFont.load_default(size=48))
        image.save(self.source, 'PDF', resolution=150)
        document = replace(self.document, source_sha256=digest(self.source.read_bytes()))
        original = self.source.read_bytes()
        output = Path(self.temp.name) / 'artifacts'
        processed = PDFVisionProcessor(self.root, config).process(document, output)
        self.assertEqual(self.source.read_bytes(), original)
        self.assertEqual(processed.blocks, document.blocks)
        self.assertEqual(processed.source_sha256, document.source_sha256)
        self.assertEqual(len(processed.images), 1)
        aid = processed.processing_aids[0]
        self.assertIn('SYNTHETIC', aid.text)
        self.assertFalse(aid.provenance['authoritative'])
        self.assertEqual(aid.provenance['image_sha256'], processed.images[0].sha256)
        self.assertEqual(aid.provenance['source_sha256'], document.source_sha256)
        self.assertEqual(aid.provenance['config']['dpi'], 300)
        self.assertIsNotNone(aid.provenance['traineddata_sha256']['eng'])
        self.assertIn('binary_sha256', aid.provenance['tools']['renderer'])
        self.assertIn('unverified_ocr:original_image_review_required', processed.warnings)
        self.assertNotEqual(processed.transformation_sha256, document.transformation_sha256)
        self.assertEqual(ParsedDocument.from_dict(processed.to_dict()), processed)
        self.error('already_processed', config, processed)
        saved = output / document.source_sha256 / 'page-1'
        self.assertEqual(digest((saved / 'ocr.tsv').read_bytes()), aid.provenance['tsv_sha256'])
        self.assertEqual(digest((saved / 'render.png').read_bytes()), processed.images[0].sha256)
        # Retain synthetic render temporarily for visual skill validation.
        if __import__('os').environ.get('KALMORA_OCR_TEST_RENDER'):
            Path(__import__('os').environ['KALMORA_OCR_TEST_RENDER']).write_bytes(processed.images[0].data)
