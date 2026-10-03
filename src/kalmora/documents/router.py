"""Read selected originals into page/field evidence without deciding accounting."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from .contracts import ParsedBlock, ParsedDocument, PageImage, digest, source_path

PARSER_VERSION = "source-router-v1/pypdf-6.19.0"
MAX_SOURCE_BYTES = 20 * 1024 * 1024


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
    def __init__(self, phase_path: str | Path):
        self.phase_path = Path(phase_path).resolve()
        if "golden" in self.phase_path.parts:
            raise ValueError("golden is not a document input")

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
        suffix = path.suffix.lower()
        blocks, images, warnings = (), (), ()
        try:
            if suffix == ".pdf":
                try:
                    from pypdf import PdfReader
                except ImportError:
                    raise ParseError(relative, "missing_documents_extra") from None
                reader = PdfReader(BytesIO(data), strict=True)
                if reader.is_encrypted:
                    raise ParseError(relative, "encrypted_pdf")
                block_list, image_list, warning_list = [], [], []
                for number, page in enumerate(reader.pages, 1):
                    text = page.extract_text(extraction_mode="layout") or ""
                    block_list.append(ParsedBlock(f"page.{number}", text, number))
                    if len(text.strip()) < 15:
                        warning_list.append(f"page.{number}:vision_required")
                        for image in page.images:
                            mime = "image/jpeg" if image.data.startswith(b"\xff\xd8") else "image/png"
                            image_list.append(PageImage(number, mime, image.data))
                        if not any(i.page == number for i in image_list):
                            raise ParseError(relative, "page_without_text_or_embedded_image")
                if not block_list:
                    raise ParseError(relative, "empty_pdf")
                blocks, images, warnings = tuple(block_list), tuple(image_list), tuple(warning_list)
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
        return ParsedDocument(relative, digest(data), media, PARSER_VERSION, blocks, images, warnings)

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
