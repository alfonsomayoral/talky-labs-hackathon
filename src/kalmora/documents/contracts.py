"""Provider-independent boundaries between original sources and interpretation."""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from decimal import Decimal
import hashlib
import json
from pathlib import PurePosixPath
from typing import Protocol

from kalmora.facts import DocumentFacts


def source_path(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("source path must be a nonempty string")
    path = PurePosixPath(value)
    if (path.is_absolute()
            or ".." in path.parts or "golden" in path.parts or "\\" in value):
        raise ValueError("source path must be relative and outside golden")
    return path.as_posix()


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def valid_hash(value: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("invalid SHA-256")


def _canonical(value):
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("nonfinite context amount")
        return ["decimal", str(value)]
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise ValueError("context dictionary keys must be strings")
        return ["dict", [[k, _canonical(v)] for k, v in sorted(value.items())]]
    if isinstance(value, (list, tuple)):
        return ["list", [_canonical(v) for v in value]]
    if value is None or isinstance(value, (str, bool, int, float)):
        return [type(value).__name__, value]
    raise ValueError("context must contain JSON values or exact Decimal values")


def fingerprint(value) -> str:
    return digest(json.dumps(_canonical(value), sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False).encode())


@dataclass(frozen=True)
class ParsedBlock:
    id: str
    text: str
    page: int | None = None
    source_field: str | None = None

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id or not isinstance(self.text, str):
            raise ValueError("block requires id and original text")
        if self.page is not None and (type(self.page) is not int or self.page < 1):
            raise ValueError("page must be a positive integer")
        if self.source_field is not None and not isinstance(self.source_field, str):
            raise ValueError("source field must be a string")


@dataclass(frozen=True)
class PageImage:
    page: int
    media_type: str
    data: bytes

    def __post_init__(self):
        if type(self.page) is not int or self.page < 1:
            raise ValueError("image page must be a positive integer")
        if self.media_type not in {"image/png", "image/jpeg", "image/webp"}:
            raise ValueError("unsupported page image type")
        if not isinstance(self.data, bytes) or not self.data:
            raise ValueError("page image requires bytes")

    @property
    def sha256(self):
        return digest(self.data)


@dataclass(frozen=True)
class ProcessingAid:
    """Unverified machine reading; never a source block or factual evidence."""
    page: int
    text: str
    provenance: dict[str, object]

    def __post_init__(self):
        if type(self.page) is not int or self.page < 1:
            raise ValueError("aid page must be a positive integer")
        if not isinstance(self.text, str):
            raise ValueError("processing aid requires text")
        if not isinstance(self.provenance, dict):
            raise ValueError("processing aid requires structured provenance")
        fingerprint(self.provenance)


@dataclass(frozen=True)
class ParsedDocument:
    path: str
    source_sha256: str
    media_type: str
    parser_version: str
    blocks: tuple[ParsedBlock, ...]
    images: tuple[PageImage, ...] = ()
    warnings: tuple[str, ...] = ()
    processing_aids: tuple[ProcessingAid, ...] = ()

    def __post_init__(self):
        source_path(self.path)
        valid_hash(self.source_sha256)
        if not self.media_type or not self.parser_version:
            raise ValueError("format and parser version are required")
        if any(not isinstance(b, ParsedBlock) for b in self.blocks):
            raise ValueError("invalid source blocks")
        if len({b.id for b in self.blocks}) != len(self.blocks):
            raise ValueError("block identities must be unique")
        if any(not isinstance(i, PageImage) for i in self.images):
            raise ValueError("invalid page images")
        if any(not isinstance(a, ProcessingAid) for a in self.processing_aids):
            raise ValueError("invalid processing aids")
        if any(a.page not in {b.page for b in self.blocks} for a in self.processing_aids):
            raise ValueError("processing aid requires an original page block")

    def to_dict(self, *, include_images=True):
        return {"schema_version": 1, "path": self.path, "source_sha256": self.source_sha256,
                "media_type": self.media_type, "parser_version": self.parser_version,
                "blocks": [{"id": b.id, "text": b.text, "page": b.page,
                            "source_field": b.source_field} for b in self.blocks],
                "images": [{"page": i.page, "media_type": i.media_type, "sha256": i.sha256,
                            **({"base64": base64.b64encode(i.data).decode()} if include_images else {})}
                           for i in self.images], "warnings": list(self.warnings),
                **({"unverified_processing_aids": [
                    {"page": a.page, "text": a.text, "provenance": a.provenance}
                    for a in self.processing_aids]} if self.processing_aids else {})}

    @classmethod
    def from_dict(cls, value):
        if value.get("schema_version") != 1:
            raise ValueError("unsupported parsed-document schema")
        images = []
        for image in value["images"]:
            data = base64.b64decode(image["base64"], validate=True)
            if digest(data) != image["sha256"]:
                raise ValueError("image content hash mismatch")
            images.append(PageImage(image["page"], image["media_type"], data))
        return cls(value["path"], value["source_sha256"], value["media_type"],
                   value["parser_version"], tuple(ParsedBlock(**b) for b in value["blocks"]),
                   tuple(images), tuple(value.get("warnings", ())),
                   tuple(ProcessingAid(**a) for a in value.get("unverified_processing_aids", ())))

    @property
    def transformation_sha256(self):
        return fingerprint(self.to_dict(include_images=False))


@dataclass(frozen=True)
class Candidate:
    id: str
    attributes: dict[str, object]

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("candidate requires an explicit ID")
        fingerprint(self.attributes)


@dataclass(frozen=True)
class ResolutionRequest:
    document: ParsedDocument
    candidates: tuple[Candidate, ...]
    context: dict[str, object] = field(default_factory=dict)

    def __post_init__(self):
        if len({c.id for c in self.candidates}) != len(self.candidates):
            raise ValueError("candidate IDs must be unique")
        fingerprint(self.context)

    @property
    def sha256(self):
        return fingerprint({"document": self.document.transformation_sha256,
                            "candidates": [{"id": c.id, "attributes": c.attributes}
                                           for c in self.candidates], "context": self.context})


@dataclass(frozen=True)
class ResolutionResult:
    status: str
    selected_ids: tuple[str, ...]
    evidence: tuple[dict[str, object], ...]
    reason: str

    def __post_init__(self):
        if self.status not in {"SELECTED", "AMBIGUOUS", "NO_MATCH"}:
            raise ValueError("invalid resolution status")
        if any(not isinstance(i, str) or not i for i in self.selected_ids):
            raise ValueError("selected IDs must be nonempty strings")
        if (self.status == "SELECTED") != bool(self.selected_ids):
            raise ValueError("selection and abstention must be explicit")
        if len(set(self.selected_ids)) != len(self.selected_ids):
            raise ValueError("duplicate selected IDs")
        if not isinstance(self.reason, str) or any(not isinstance(e, dict) for e in self.evidence):
            raise ValueError("resolution requires reason and structured evidence")
        fingerprint(self.evidence)

    def to_dict(self):
        return {"schema_version": 1, "status": self.status,
                "selected_ids": list(self.selected_ids), "evidence": list(self.evidence), "reason": self.reason}

    @classmethod
    def from_dict(cls, value):
        if value.get("schema_version") != 1:
            raise ValueError("unsupported resolution schema")
        return cls(value["status"], tuple(value["selected_ids"]), tuple(value["evidence"]), value["reason"])


class DocumentExtractor(Protocol):
    async def extract(self, document: ParsedDocument) -> DocumentFacts: ...


class SemanticResolver(Protocol):
    async def resolve(self, request: ResolutionRequest) -> ResolutionResult: ...
