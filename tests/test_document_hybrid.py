"""Dispatch tests use only injected extractors; no live provider is involved."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import unittest

from kalmora.documents.contracts import (
    PageImage, ParsedBlock, ParsedDocument, ProcessingAid, digest,
)
from kalmora.documents.hybrid import HybridDocumentExtractor, HybridExtractionError
from kalmora.facts import DocumentFacts


def make_document(*, media_type="application/pdf", images=(), warnings=(),
                  blocks=None, aids=(), parser_version="router-v1"):
    blocks = blocks if blocks is not None else (ParsedBlock("page.1", "Native text", 1),)
    return ParsedDocument(
        "inbox/ap/sample/source.pdf", digest(b"original source bytes"), media_type,
        parser_version, tuple(blocks), tuple(images), tuple(warnings), tuple(aids),
    )


class FakeExtractor:
    def __init__(self, version):
        self.version = version
        self.calls = []
        self.result = None

    async def extract(self, document):
        self.calls.append(document)
        if self.result is not None:
            return self.result
        return DocumentFacts(document.source_sha256, self.version, {})


class HybridDocumentExtractorTests(unittest.IsolatedAsyncioTestCase):
    async def test_xml_uses_default_xml_extractor_without_calling_injected_models(self):
        native, vision = FakeExtractor("native-v1"), FakeExtractor("vision-v1")
        xml = make_document(
            media_type="application/xml",
            blocks=(ParsedBlock("version", "4.0", source_field="/Comprobante/@Version"),),
        )

        facts = await HybridDocumentExtractor(native, vision).extract(xml)

        self.assertEqual(facts.extractor_version, "xml-source-extractor-v2")
        self.assertEqual(facts.fields["raw.xml./Comprobante/@Version"][0].value, "4.0")
        self.assertEqual(native.calls, [])
        self.assertEqual(vision.calls, [])

    async def test_native_pdf_and_images_dispatch_to_the_matching_adapter(self):
        native, vision = FakeExtractor("native-v1"), FakeExtractor("vision-v1")
        adapter = HybridDocumentExtractor(native, vision)
        native_doc = make_document()
        image = PageImage(1, "image/png", b"prepared image bytes")
        prepared_pdf = make_document(
            images=(image,), warnings=("page.1:vision_required",),
            parser_version="router-v1/pdf-prepared:test",
        )
        png = make_document(media_type="image/png", images=(image,),
                            warnings=("page.1:vision_required",))

        native_facts = await adapter.extract(native_doc)
        pdf_facts = await adapter.extract(prepared_pdf)
        image_facts = await adapter.extract(png)

        self.assertEqual(native_facts.extractor_version, "native-v1")
        self.assertEqual(pdf_facts.extractor_version, "vision-v1")
        self.assertEqual(image_facts.extractor_version, "vision-v1")
        self.assertIs(native.calls[0], native_doc)
        self.assertEqual(vision.calls, [prepared_pdf, png])

    async def test_missing_required_page_image_fails_before_any_extractor_call(self):
        native, vision = FakeExtractor("native-v1"), FakeExtractor("vision-v1")
        other_page = PageImage(1, "image/png", b"page one")
        source = make_document(
            images=(other_page,), warnings=("page.2:vision_required",),
            blocks=(ParsedBlock("page.1", "Page 1 text", 1),
                    ParsedBlock("page.2", "", 2)),
        )

        with self.assertRaises(HybridExtractionError) as caught:
            await HybridDocumentExtractor(native, vision).extract(source)

        self.assertEqual(caught.exception.category, "vision_image_missing")
        self.assertEqual(native.calls, [])
        self.assertEqual(vision.calls, [])

    async def test_adapter_preserves_prepared_source_and_conflicting_result_verbatim(self):
        image = PageImage(1, "image/png", b"prepared image bytes")
        aid = ProcessingAid(1, "unverified OCR suggestion", {
            "kind": "unverified_ocr", "authoritative": False,
        })
        source = make_document(
            images=(image,), warnings=("page.1:vision_required",),
            blocks=(ParsedBlock("page.1", "Original extracted source text", 1),),
            aids=(aid,), parser_version="router-v1/pdf-prepared:source-fingerprint",
        )
        before = source.to_dict()
        conflicting = DocumentFacts(digest(b"another source"), "foreign-extractor-v9", {})
        native, vision = FakeExtractor("native-v1"), FakeExtractor("vision-v1")
        vision.result = conflicting

        result = await HybridDocumentExtractor(native, vision).extract(source)

        self.assertIs(result, conflicting)
        self.assertEqual(result.source_sha256, digest(b"another source"))
        self.assertEqual(source.to_dict(), before)
        self.assertIs(vision.calls[0], source)
        self.assertEqual(vision.calls[0].transformation_sha256, source.transformation_sha256)

    async def test_import_does_not_load_llm_sdk_or_provider_extractor(self):
        source_root = Path(__file__).resolve().parents[1] / "src"
        environment = dict(os.environ, PYTHONPATH=str(source_root))
        code = (
            "import sys; import kalmora.documents.hybrid; "
            "assert 'openai' not in sys.modules; "
            "assert 'pydantic' not in sys.modules; "
            "assert 'kalmora.documents.extractor' not in sys.modules; "
            "assert 'kalmora.llm.client' not in sys.modules"
        )
        completed = subprocess.run(
            [sys.executable, "-c", code], env=environment,
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
