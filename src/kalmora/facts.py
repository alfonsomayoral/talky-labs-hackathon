"""Evidence-preserving document facts; format extractors are supplied by callers."""
from dataclasses import asdict, dataclass
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
from typing import Any
import tempfile


def _encode_value(value: object) -> Any:
    """Tag every container so a source dictionary cannot mimic a Decimal tag."""
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("Fact Decimal values must be finite")
        return {"type": "decimal", "value": str(value)}
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("Fact dictionaries require string keys")
        return {"type": "dict", "items": [[key, _encode_value(item)] for key, item in value.items()]}
    if isinstance(value, list):
        return {"type": "list", "items": [_encode_value(item) for item in value]}
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise TypeError(f"Unsupported fact value type: {type(value).__name__}")


def _decode_value(value: object) -> Any:
    if not isinstance(value, dict):
        return value
    if value.get("type") == "decimal" and set(value) == {"type", "value"}:
        result = Decimal(value["value"])
        if not result.is_finite():
            raise ValueError("Fact Decimal values must be finite")
        return result
    if value.get("type") == "dict" and set(value) == {"type", "items"}:
        return {key: _decode_value(item) for key, item in value["items"]}
    if value.get("type") == "list" and set(value) == {"type", "items"}:
        return [_decode_value(item) for item in value["items"]]
    raise ValueError("Invalid typed fact value")


def atomic_json(path: str | Path, value: Any) -> None:
    """Write JSON via a temp file + fsync + rename, so readers never see a partial file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            name = stream.name
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


@dataclass(frozen=True)
class Evidence:
    """Where a value was read: the proof that lets a decision be traced and audited."""

    document: str
    """Attachment or source name (file name, message id)."""

    field: str
    """Field or location inside the document the value was read from."""

    page: int | None = None
    """1-based page for paginated sources; ``None`` when not applicable."""

    quote: str | None = None
    """Literal text supporting the value, when available."""

    def __post_init__(self) -> None:
        if (not isinstance(self.document, str) or not self.document
                or not isinstance(self.field, str) or not self.field
                or (self.page is not None and (type(self.page) is not int or self.page < 1))
                or (self.quote is not None and not isinstance(self.quote, str))):
            raise ValueError("Evidence requires document, field and a positive page when supplied")


@dataclass(frozen=True)
class Fact:
    """One candidate value for a field together with its evidence.

    Contradictory candidates are kept as separate facts, never merged.
    """

    value: object
    """Extracted value: str, int, bool, float, None, Decimal, or nested list/dict of those."""

    evidence: Evidence

    def __post_init__(self) -> None:
        if not isinstance(self.evidence, Evidence):
            raise ValueError("Fact requires structured Evidence")


@dataclass(frozen=True)
class DocumentFacts:
    """Everything an extractor found in one attachment.

    Identity is the attachment's bytes plus the extractor version; changing either
    yields a different ``FactsCache`` key.
    """

    source_sha256: str
    """Lowercase hex SHA-256 of the original attachment bytes."""

    extractor_version: str
    """Version of the extractor that produced the facts."""

    fields: dict[str, list[Fact]]
    """Field name -> every candidate found (possibly contradictory), each with evidence."""

    def __post_init__(self) -> None:
        if (not isinstance(self.source_sha256, str) or len(self.source_sha256) != 64
                or any(c not in "0123456789abcdef" for c in self.source_sha256)):
            raise ValueError("Invalid source SHA-256")
        if not isinstance(self.extractor_version, str) or not self.extractor_version:
            raise ValueError("Extractor version is required")
        if (not isinstance(self.fields, dict) or any(not isinstance(key, str) or not key
                or not isinstance(values, list) or any(not isinstance(fact, Fact) for fact in values)
                for key, values in self.fields.items())):
            raise ValueError("Fields require named lists of Fact objects")

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form (``typed-v1`` encoding keeps Decimal exact)."""
        return {"source_sha256": self.source_sha256, "extractor_version": self.extractor_version,
                "fact_value_encoding": "typed-v1", "fields": {
                    key: [{"value": _encode_value(fact.value), "evidence": asdict(fact.evidence)}
                          for fact in values] for key, values in self.fields.items()}}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentFacts":
        """Inverse of ``to_dict``; ValueError for an unsupported encoding."""
        encoding = data.get("fact_value_encoding")
        if encoding not in (None, "typed-v1"):
            raise ValueError("Unsupported fact value encoding")
        return cls(data["source_sha256"], data["extractor_version"], {
            key: [Fact(_decode_value(f["value"]) if encoding else f["value"],
                       Evidence(**f["evidence"])) for f in values]
            for key, values in data["fields"].items()})


class FactsCache:
    """One entry per attachment bytes/config/version; never coalesces conflicting facts."""
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)

    @staticmethod
    def key(source: bytes, extractor_version: str, config: dict[str, Any] | None = None) -> str:
        payload = json.dumps({"source_sha256": hashlib.sha256(source).hexdigest(),
                              "extractor_version": extractor_version, "config": config or {}},
                             sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return hashlib.sha256(payload).hexdigest()

    def load(self, source: bytes, extractor_version: str,
             config: dict[str, Any] | None = None) -> DocumentFacts | None:
        """Cached facts for these bytes/version/config, or ``None`` on a miss."""
        path = self.directory / (self.key(source, extractor_version, config) + ".json")
        if not path.exists():
            return None
        facts = DocumentFacts.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if facts.source_sha256 != hashlib.sha256(source).hexdigest() or facts.extractor_version != extractor_version:
            raise ValueError("Cache metadata mismatch")
        return facts

    def store(self, source: bytes, facts: DocumentFacts, config: dict[str, Any] | None = None) -> Path:
        """Write ``facts`` atomically; ValueError if they refer to other bytes."""
        if facts.source_sha256 != hashlib.sha256(source).hexdigest():
            raise ValueError("Facts must refer to the supplied original bytes")
        path = self.directory / (self.key(source, facts.extractor_version, config) + ".json")
        atomic_json(path, facts.to_dict())
        return path
