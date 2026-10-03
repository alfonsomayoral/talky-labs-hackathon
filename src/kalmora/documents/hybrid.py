"""Provider-independent dispatch across native text, page images, and XML."""
from __future__ import annotations

import re
from typing import Protocol

from kalmora.facts import DocumentFacts
from .contracts import ParsedDocument
from .xml_extractor import XMLDocumentExtractor


class DocumentFactsExtractor(Protocol):
    async def extract(self, document: ParsedDocument) -> DocumentFacts: ...


class HybridExtractionError(ValueError):
    """A prepared source cannot be safely sent to the selected extractor."""

    def __init__(self, category: str, document: ParsedDocument):
        self.category = category
        self.path = document.path
        self.source_sha256 = document.source_sha256
        super().__init__(f"{document.path}: {category}")


class HybridDocumentExtractor:
    """Dispatch an already prepared source without changing or caching it.

    Preparation, including PDF page rendering, must happen before the caller
    computes its recording key. This adapter forwards that exact
    ``ParsedDocument`` to one injected extractor and returns its facts unchanged.
    """

    def __init__(self, native: DocumentFactsExtractor,
                 vision: DocumentFactsExtractor,
                 xml: DocumentFactsExtractor | None = None):
        for name, extractor in (("native", native), ("vision", vision)):
            if not callable(getattr(extractor, "extract", None)):
                raise TypeError(f"{name} extractor must implement async extract(document)")
        if xml is not None and not callable(getattr(xml, "extract", None)):
            raise TypeError("xml extractor must implement async extract(document)")
        self.native = native
        self.vision = vision
        self.xml = xml if xml is not None else XMLDocumentExtractor()

    @staticmethod
    def _vision_required_pages(document: ParsedDocument) -> set[int]:
        return {int(match.group(1)) for warning in document.warnings
                if (match := re.fullmatch(r"page\.(\d+):vision_required", warning))}

    def _select(self, document: ParsedDocument) -> DocumentFactsExtractor:
        # XML is deterministic and never reaches a provider-backed extractor.
        if document.media_type in {"application/xml", "text/xml"}:
            return self.xml

        if document.media_type == "application/pdf":
            required = self._vision_required_pages(document)
            retained_pages = {image.page for image in document.images}
            if required - retained_pages:
                raise HybridExtractionError("vision_image_missing", document)
            if required or document.images:
                return self.vision
            return self.native

        if document.media_type.startswith("image/"):
            if not document.images:
                raise HybridExtractionError("vision_image_missing", document)
            return self.vision

        if document.images:
            return self.vision
        return self.native

    async def extract(self, document: ParsedDocument) -> DocumentFacts:
        """Extract facts from this exact prepared source with its selected adapter."""
        if not isinstance(document, ParsedDocument):
            raise TypeError("HybridDocumentExtractor requires a prepared ParsedDocument")
        extractor = self._select(document)
        return await extractor.extract(document)
