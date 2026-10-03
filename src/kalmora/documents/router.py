"""Read selected originals into page/field evidence without deciding accounting."""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
import re
import unicodedata
import xml.etree.ElementTree as ET

from .contracts import ParsedBlock, ParsedDocument, PageImage, digest, source_path

PARSER_VERSION = "source-router-v3/pypdf-6.19.0"
MAX_SOURCE_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 64
MAX_PDF_FRAGMENTS_PER_PAGE = 10_000
MAX_PDF_FRAGMENTS_TOTAL = 100_000
MAX_PDF_FRAGMENT_CHARS = 5_000_000


def _text_layer_reason(text: str) -> str | None:
    """Routing hints, never repairs or assertions that an extracted layer is true."""
    if len(text.strip()) < 15:
        return "sparse_text_layer"
    if ("\ufffd" in text or re.search(r"\(cid:\d+\)", text)
            or any(unicodedata.category(char) in {"Cc", "Co", "Cs", "Cn"}
                   and char not in "\t\n\r\f" for char in text)):
        return "suspect_text_layer"
    return None


def _has_raster_content(page) -> bool:
    """Inspect PDF resources/operators without decoding embedded image pixels.

    Even a small raster can carry omitted text. Conservatively render such pages,
    including logos, rather than declaring a native layer complete by its length.
    """
    pending, visited = [page], set()
    while pending:
        obj = pending.pop().get_object()
        if id(obj) in visited:
            continue
        visited.add(id(obj))
        if len(visited) > 1000:
            raise ValueError("PDF resource traversal limit")
        # Page resources may be inherited from an ancestor /Pages node.
        # Form XObjects use their own resource dictionary when present.
        resources = (obj.get_inherited("/Resources", {}) if obj.get("/Type") == "/Page"
                     else obj.get("/Resources", {}))
        resources = resources.get_object() if hasattr(resources, "get_object") else resources
        xobjects = resources.get("/XObject", {})
        xobjects = xobjects.get_object() if hasattr(xobjects, "get_object") else xobjects
        for reference in xobjects.values():
            child = reference.get_object()
            if child.get("/Subtype") == "/Image":
                return True
            if child.get("/Subtype") == "/Form":
                pending.append(child)
                # Inline raster data can also occur inside a Form XObject.
                from pypdf.generic import ContentStream
                if any(operator == b"INLINE IMAGE" for _, operator in
                       ContentStream(child, page.pdf).operations):
                    return True
    content = page.get_contents()
    return bool(content and any(operator == b"INLINE IMAGE"
                                for _, operator in content.operations))


class ParseError(ValueError):
    def __init__(self, path: str, category: str):
        super().__init__(f"{path}: {category}")
        self.path, self.category = path, category


@dataclass(frozen=True)
class ParsedFolder:
    documents: tuple[ParsedDocument, ...]
    errors: tuple[ParseError, ...]


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _xml_blocks(data: bytes):
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise ValueError("XML entity declarations are unsupported")
    root = ET.fromstring(data)
    blocks = []

    def visit(element, path):
        if element.text and element.text.strip():
            blocks.append(ParsedBlock(path, element.text.strip(), source_field=path))
        elif not len(element) and not element.attrib:
            blocks.append(ParsedBlock(path, "", source_field=path))
        for name, value in sorted(element.attrib.items()):
            field = path + "/@" + _local(name)
            blocks.append(ParsedBlock(field, value, source_field=field))
        counts = {}
        for child in element:
            name = _local(child.tag)
            counts[name] = counts.get(name, 0) + 1
            visit(child, path + "/" + name + f"[{counts[name]}]")

    visit(root, "/" + _local(root.tag))
    return tuple(blocks)


class DocumentRouter:
    def __init__(self, phase_path: str | Path, *, use_preparsed: bool = False,
                 normalized_dir: str | Path | None = None):
        self.phase_path = Path(phase_path).resolve()
        if "golden" in self.phase_path.parts:
            raise ValueError("golden is not a document input")
        if type(use_preparsed) is not bool:
            raise TypeError("use_preparsed must be a boolean")
        self.use_preparsed = use_preparsed
        self.normalized_dir = (Path(normalized_dir).resolve() if normalized_dir is not None
                               else self.phase_path.parent / "normalized_sources")

    def _path(self, relative: str):
        source_path(relative)
        path = (self.phase_path / relative).resolve()
        if not path.is_relative_to(self.phase_path) or "golden" in path.parts:
            raise ValueError("source escapes active phase")
        if not relative.startswith("inbox/"):
            raise ValueError("document router reads inbox originals only")
        return path

    def parse(self, relative: str) -> ParsedDocument:
        path = self._path(relative)
        if not path.is_file():
            raise ParseError(relative, "missing_source")
        if path.stat().st_size > MAX_SOURCE_BYTES:
            raise ParseError(relative, "source_size_limit")
        data = path.read_bytes()
        if len(data) > MAX_SOURCE_BYTES:
            raise ParseError(relative, "source_size_limit")
        if self.use_preparsed:
            return self._load_preparsed(relative, data)
        suffix = path.suffix.lower()
        parser_version = PARSER_VERSION
        blocks, images, warnings = (), (), ()
        try:
            if suffix == ".pdf":
                try:
                    from pypdf import PdfReader, __version__ as pypdf_version
                except ImportError:
                    raise ParseError(relative, "missing_documents_extra") from None
                reader = PdfReader(BytesIO(data), strict=True)
                parser_version += "/pypdf-" + pypdf_version
                if reader.is_encrypted:
                    raise ParseError(relative, "encrypted_pdf")
                if len(reader.pages) > MAX_PDF_PAGES:
                    raise ParseError(relative, "page_limit")
                block_list, warning_list = [], []
                fragment_chars = fragment_count = 0
                for number, page in enumerate(reader.pages, 1):
                    reasons = []
                    try:
                        text = page.extract_text(extraction_mode="layout") or ""
                    except Exception:
                        text = ""
                        reasons.append("text_extraction_failed")
                    block_list.append(ParsedBlock(f"page.{number}", text, number))
                    page_fragments = []
                    page_fragment_count = 0
                    fragment_limit = False

                    def capture_text_chunk(chunk, *_visitor_args):
                        nonlocal fragment_chars, fragment_count, page_fragment_count, fragment_limit
                        if not isinstance(chunk, str):
                            raise TypeError("visitor_text chunk must be text")
                        if not chunk:
                            return
                        if (page_fragment_count >= MAX_PDF_FRAGMENTS_PER_PAGE
                                or fragment_count >= MAX_PDF_FRAGMENTS_TOTAL
                                or fragment_chars + len(chunk) > MAX_PDF_FRAGMENT_CHARS):
                            fragment_limit = True
                            return
                        page_fragment_count += 1
                        fragment_count += 1
                        fragment_chars += len(chunk)
                        fragment_id = f"page.{number}.fragment.{page_fragment_count}"
                        page_fragments.append(ParsedBlock(
                            fragment_id, chunk, number, source_field=fragment_id))

                    try:
                        # This is a second, ordinary visitor extraction. Keep the
                        # existing layout block byte-for-byte unchanged; callbacks
                        # preserve pypdf's native text chunks and content order.
                        page.extract_text(visitor_text=capture_text_chunk)
                    except Exception:
                        reasons.append("text_fragment_extraction_failed")
                    else:
                        if fragment_limit:
                            reasons.append("text_fragment_limit")
                    block_list.extend(page_fragments)
                    if reason := _text_layer_reason(text):
                        reasons.append(reason)
                    try:
                        if _has_raster_content(page):
                            reasons.append("raster_content")
                    except Exception:
                        reasons.append("image_inspection_failed")
                    if reasons:
                        warning_list.append(f"page.{number}:vision_required")
                        warning_list.extend(f"page.{number}:{reason}" for reason in reasons)
                if not block_list:
                    raise ParseError(relative, "empty_pdf")
                # Embedded images are fragments: they can omit vectors, stamps and
                # other images. PDFVisionProcessor renders the complete page.
                blocks, warnings = tuple(block_list), tuple(warning_list)
                media = "application/pdf"
            elif suffix == ".xml":
                blocks = _xml_blocks(data)
                media = "application/xml"
            elif suffix == ".json":
                original = data.decode("utf-8")
                json.loads(original, parse_float=Decimal, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
                blocks = (ParsedBlock("json", original,
                                      source_field="/"),)
                media = "application/json"
            elif suffix in {".txt", ".csv", ".eml"}:
                blocks = (ParsedBlock("text", data.decode("utf-8"), source_field="text"),)
                media = "text/plain"
            elif suffix in {".png", ".jpg", ".jpeg", ".webp"}:
                media = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}[suffix]
                images = (PageImage(1, media, data),)
                blocks = (ParsedBlock("page.1", "", 1),)
                warnings = ("page.1:vision_required",)
            else:
                raise ParseError(relative, "unsupported_format")
        except ParseError:
            raise
        except Exception:
            raise ParseError(relative, "invalid_" + suffix.lstrip(".")) from None
        return ParsedDocument(relative, digest(data), media, parser_version, blocks, images, warnings)

    def _load_preparsed(self, relative: str, source: bytes) -> ParsedDocument:
        """Load a prior router snapshot, tied to these exact source bytes.

        This opt-in path is a development shortcut. It never falls back to
        parsing when the snapshot is absent, invalid, or stale.
        """
        snapshot_path = self.normalized_dir / self.phase_path.name / (relative + ".json")
        if not snapshot_path.is_file():
            raise ParseError(relative, "missing_preparsed_snapshot")
        try:
            value = json.loads(snapshot_path.read_text(encoding="utf-8"))
            document = ParsedDocument.from_dict(value)
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            raise ParseError(relative, "invalid_preparsed_snapshot") from None
        expected_path = f"{self.phase_path.name}/{relative}"
        if document.path not in {relative, expected_path}:
            raise ParseError(relative, "preparsed_path_mismatch")
        if document.source_sha256 != digest(source):
            raise ParseError(relative, "preparsed_source_hash_mismatch")
        # The corpus dump is participant-relative; router consumers use paths
        # relative to the selected phase. Preserve that existing contract.
        return replace(document, path=relative)

    def parse_folder(self, relative: str) -> ParsedFolder:
        path = self._path(relative)
        if not path.is_dir():
            raise ParseError(relative, "missing_folder")
        documents, errors = [], []
        for child in sorted(path.iterdir()):
            if not child.is_file():
                continue
            try:
                documents.append(self.parse(child.relative_to(self.phase_path).as_posix()))
            except ParseError as error:
                errors.append(error)
        return ParsedFolder(tuple(documents), tuple(errors))
