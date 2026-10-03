"""Evidence-preserving document facts; format extractors are supplied by callers."""
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import tempfile


def atomic_json(path, value):
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
    document: str
    field: str
    page: int | None = None
    quote: str | None = None

    def __post_init__(self):
        if not self.document or not self.field or (self.page is not None and self.page < 1):
            raise ValueError("Evidence requires document, field and a positive page when supplied")


@dataclass(frozen=True)
class Fact:
    value: object
    evidence: Evidence


@dataclass(frozen=True)
class DocumentFacts:
    source_sha256: str
    extractor_version: str
    fields: dict[str, list[Fact]]

    def __post_init__(self):
        if len(self.source_sha256) != 64 or any(c not in "0123456789abcdef" for c in self.source_sha256):
            raise ValueError("Invalid source SHA-256")
        if not self.extractor_version:
            raise ValueError("Extractor version is required")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(data["source_sha256"], data["extractor_version"], {
            key: [Fact(f["value"], Evidence(**f["evidence"])) for f in values]
            for key, values in data["fields"].items()})


class FactsCache:
    """One entry per attachment bytes/config/version; never coalesces conflicting facts."""
    def __init__(self, directory):
        self.directory = Path(directory)

    @staticmethod
    def key(source: bytes, extractor_version: str, config=None):
        payload = json.dumps({"source_sha256": hashlib.sha256(source).hexdigest(),
                              "extractor_version": extractor_version, "config": config or {}},
                             sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        return hashlib.sha256(payload).hexdigest()

    def load(self, source, extractor_version, config=None):
        path = self.directory / (self.key(source, extractor_version, config) + ".json")
        if not path.exists():
            return None
        facts = DocumentFacts.from_dict(json.loads(path.read_text(encoding="utf-8")))
        if facts.source_sha256 != hashlib.sha256(source).hexdigest() or facts.extractor_version != extractor_version:
            raise ValueError("Cache metadata mismatch")
        return facts

    def store(self, source, facts, config=None):
        if facts.source_sha256 != hashlib.sha256(source).hexdigest():
            raise ValueError("Facts must refer to the supplied original bytes")
        path = self.directory / (self.key(source, facts.extractor_version, config) + ".json")
        atomic_json(path, facts.to_dict())
        return path
