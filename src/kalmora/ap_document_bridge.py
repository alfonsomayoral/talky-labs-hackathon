"""Typed AP observations from normalized attachments, without policy inference.

Headers can reach consensus across attachments. Invoice rows retain their
attachment and row identity: position 1 in a PDF is not position 1 in an XML
until a caller establishes that relationship from evidence.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re
from types import MappingProxyType
from typing import Generic, TypeVar

from .ap_rejections import UNKNOWN, resolve_field
from .documents.classification import DocumentClassification, DOCUMENT_TYPES, classify_document
from .documents.contracts import source_path as validate_source_path
from .documents.normalization import NormalizationDiagnostic, NormalizedDocument
from .facts import Evidence, Fact

DOCUMENT_BRIDGE_VERSION = "ap-document-bridge-v1"
T = TypeVar("T")
_LINE = re.compile(r"line\.([1-9]\d*)\.(.+)")
_ALIASES = {
    "issuer_tax_id": "supplier_tax_id", "invoice_number": "document_number",
    "invoice_date": "document_date", "document_currency": "currency",
    "purchase_order_reference": "po_reference",
}
_REFERENCES = frozenset({"po_reference", "po_item", "receipt_reference", "delivery_reference",
    "contract_reference", "project_reference", "original_invoice_reference", "credit_note_reference",
    "receiver_transaction_reference", "issuer_transaction_reference", "receiver_contract_reference",
    "issuer_contract_reference", "order_sequence", "material"})


@dataclass(frozen=True)
class APField(Generic[T]):
    """Consensus plus all source candidates; UNKNOWN never becomes observed absence."""
    name: str
    status: str  # RESOLVED, MISSING, UNKNOWN, CONFLICT, INVALID
    value: T | None
    candidates: tuple[Fact, ...]
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...] = ()

    @property
    def known(self) -> bool:
        return self.status == "RESOLVED"

    @property
    def date_value(self) -> date | None:
        """Dates stay ISO strings for existing AP contracts; expose a typed view."""
        if self.known and isinstance(self.value, str):
            try:
                return date.fromisoformat(self.value)
            except ValueError:
                pass
        return None


def _canonical(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise ValueError("AP field requires a nonempty name")
    return _ALIASES.get(name, name)


def _kind_valid(value: object, kind: str) -> bool:
    if value is None:
        return True
    if kind == "text":
        return isinstance(value, str)
    if kind == "integer":
        return type(value) is int
    if kind == "date":
        if not isinstance(value, str):
            return False
        try:
            return date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False
    if kind == "currency":
        return isinstance(value, str) and bool(re.fullmatch(r"[A-Z]{3}", value))
    if kind == "decimal":
        return isinstance(value, Decimal) and value.is_finite()
    if isinstance(value, float):
        return False
    if isinstance(value, Decimal):
        return value.is_finite()
    if isinstance(value, Mapping):
        return all(_kind_valid(item, "any") for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_kind_valid(item, "any") for item in value)
    return True


def _resolve(name: str, candidates: tuple[Fact, ...], kind: str = "any") -> APField:
    value, evidence, diagnostics = resolve_field({name: candidates}, name)
    if any(not _kind_valid(fact.value, kind) for fact in candidates):
        return APField(name, "INVALID", None, candidates, evidence,
                       (*diagnostics, f"INVALID_{kind.upper()}:{name}"))
    if value is UNKNOWN:
        return APField(name, "CONFLICT" if candidates else "UNKNOWN", None,
                       candidates, evidence, diagnostics)
    if value is None or isinstance(value, str) and not value.strip():
        return APField(name, "MISSING", value, candidates, evidence)
    return APField(name, "RESOLVED", value, candidates, evidence)


def _scaled_integer(value: int, exponent: int) -> Decimal:
    # Tuple construction does not round under a caller's Decimal context.
    source = Decimal(value).as_tuple()
    return Decimal((source.sign, source.digits, source.exponent + exponent))


@dataclass(frozen=True)
class APHeaderFacts:
    issuer_tax_id: APField[str]
    recipient_tax_id: APField[str]
    invoice_number: APField[str]
    invoice_date: APField[str]
    currency: APField[str]
    net_cents: APField[int]
    tax_cents: APField[int]
    gross_cents: APField[int]
    payable_cents: APField[int]
    withholding_cents: APField[int]
    retention_cents: APField[int]


class APFactSet:
    """Snapshot of candidate lists, with explicit typed access and no defaults."""
    def __init__(self, fields: Mapping[str, Iterable[Fact]], *, aliases: bool = True) -> None:
        copied: dict[str, tuple[Fact, ...]] = {}
        for key, values in fields.items():
            if not isinstance(key, str) or not key:
                raise ValueError("AP facts require named fields")
            candidates = tuple(deepcopy(tuple(values)))
            if any(not isinstance(fact, Fact) for fact in candidates):
                raise TypeError("AP facts require Fact candidates")
            copied[key] = candidates
        self._fields = copied
        self._aliases = aliases

    @property
    def fields(self) -> Mapping[str, tuple[Fact, ...]]:
        return MappingProxyType(deepcopy(self._fields))

    def field(self, name: str, *, kind: str = "any") -> APField:
        if kind not in {"any", "text", "integer", "date", "currency", "decimal"}:
            raise ValueError("unsupported explicit AP field type")
        canonical = _canonical(name) if self._aliases else name
        if not isinstance(canonical, str) or not canonical:
            raise ValueError("AP field requires a nonempty name")
        return _resolve(canonical, deepcopy(self._fields.get(canonical, ())), kind)

    def text(self, name: str) -> APField[str]:
        return self.field(name, kind="text")

    def integer(self, name: str) -> APField[int]:
        return self.field(name, kind="integer")

    def date(self, name: str) -> APField[str]:
        return self.field(name, kind="date")

    def scaled(self, name: str, exponent: int) -> APField[Decimal]:
        """Exact decimal view of integer normalized units, retaining every proof."""
        if type(exponent) is not int:
            raise TypeError("unit exponent must be integer")
        original = self.integer(name)
        if original.status == "INVALID":
            return APField(original.name, original.status, None, original.candidates,
                           original.evidence, original.diagnostics)
        candidates = tuple(Fact(None if f.value is None else _scaled_integer(f.value, exponent),
                                f.evidence) for f in original.candidates)
        return _resolve(original.name, candidates, "decimal")

    @property
    def header(self) -> APHeaderFacts:
        return APHeaderFacts(self.text("supplier_tax_id"), self.text("recipient_tax_id"),
            self.text("document_number"), self.date("document_date"),
            self.field("currency", kind="currency"), self.integer("net_cents"),
            self.integer("tax_cents"), self.integer("gross_cents"), self.integer("payable_cents"),
            self.integer("withholding_cents"), self.integer("retention_cents"))

    @property
    def references(self) -> Mapping[str, APField]:
        return MappingProxyType({name: self.field(name) for name in self._fields
            if name in _REFERENCES or name.startswith(("delivery.", "corrective.", "related."))})


@dataclass(frozen=True)
class APLineFacts:
    source_path: str
    index: int
    facts: APFactSet

    @property
    def line_id(self) -> str:
        return f"{self.source_path}#line={self.index}"

    def field(self, name: str, *, kind: str = "any") -> APField:
        return self.facts.field(name, kind=kind)

    @property
    def quantity_milli(self) -> APField[int]:
        return self.facts.integer("quantity_milli")

    @property
    def quantity(self) -> APField[Decimal]:
        return self.facts.scaled("quantity_milli", -3)

    @property
    def unit_price_e4(self) -> APField[int]:
        return self.facts.integer("unit_price_e4")

    @property
    def unit_price_cents(self) -> APField[Decimal]:
        return self.facts.scaled("unit_price_e4", -2)

    @property
    def uom(self) -> APField[str]:
        return self.facts.text("uom")

    @property
    def amount_cents(self) -> APField[int]:
        # amount and net are distinct observations; this never guesses an alias.
        return self.facts.integer("amount_cents")

    @property
    def net_cents(self) -> APField[int]:
        return self.facts.integer("net_cents")

    @property
    def references(self) -> Mapping[str, APField]:
        return self.facts.references


@dataclass(frozen=True)
class APSourceView:
    source_path: str
    source_sha256: str
    facts: APFactSet
    raw: APFactSet
    classification: DocumentClassification
    lines: tuple[APLineFacts, ...]
    diagnostics: tuple[str, ...]
    extraction_unknowns: tuple[object, ...] = ()
    normalization_diagnostics: tuple[NormalizationDiagnostic, ...] = ()

    @classmethod
    def from_normalized(cls, document: NormalizedDocument, *, source_path: str,
                        classification: DocumentClassification | None = None,
                        unknowns: Iterable[object] = ()) -> "APSourceView":
        """One attachment only. The runner can supply its format-aware classifier."""
        if not isinstance(document, NormalizedDocument):
            raise TypeError("source view requires NormalizedDocument")
        path = validate_source_path(source_path)
        document = deepcopy(document)
        if document.raw.source_sha256 != document.facts.source_sha256:
            raise ValueError("raw and normalized facts refer to different original bytes")
        for source in (document.raw, document.facts):
            if any(f.evidence.document != path for facts in source.fields.values() for f in facts):
                raise ValueError("AP attachment facts must carry the supplied source path")
        classified = deepcopy(classification) if classification is not None else classify_document(document.raw)
        if not isinstance(classified, DocumentClassification):
            raise TypeError("source classification requires DocumentClassification")
        if (classified.status not in {"CLASSIFIED", "UNKNOWN", "CONFLICT"}
                or (classified.status == "CLASSIFIED") != (classified.document_type in DOCUMENT_TYPES)
                or classified.status != "CLASSIFIED" and classified.document_type is not None
                or classified.status == "CLASSIFIED" and not classified.evidence
                or any(f.evidence.document != path for f in classified.evidence)
                or any(f.evidence.document != path for d in classified.diagnostics for f in d.evidence)):
            raise ValueError("classification must retain this attachment's evidence and explicit status")
        line_fields: dict[int, dict[str, tuple[Fact, ...]]] = {}
        for name, candidates in document.facts.fields.items():
            match = _LINE.fullmatch(name)
            if match:
                line_fields.setdefault(int(match[1]), {})[match[2]] = tuple(candidates)
        lines = tuple(APLineFacts(path, index, APFactSet(fields)) for index, fields in sorted(line_fields.items()))
        diagnostics = tuple(f"{d.code}:{d.field}" for d in document.diagnostics)
        if lines and [line.index for line in lines] != list(range(1, lines[-1].index + 1)):
            diagnostics += ("LINE_INDEX_GAP",)
        return cls(path, document.facts.source_sha256, APFactSet(document.facts.fields),
                   APFactSet(document.raw.fields, aliases=False), classified, lines, diagnostics,
                   tuple(deepcopy(tuple(unknowns))), document.diagnostics)

    def field(self, name: str, *, kind: str = "any") -> APField:
        return self.facts.field(name, kind=kind)

    @property
    def header(self) -> APHeaderFacts:
        return self.facts.header

    @property
    def references(self) -> Mapping[str, APField]:
        return self.facts.references


@dataclass(frozen=True)
class APSourceIssue:
    """Uninterpreted/failed attachment, kept outside accounting facts."""
    source_path: str
    diagnostic: str
    extraction_unknowns: tuple[object, ...] = ()

    def __post_init__(self):
        validate_source_path(self.source_path)
        if not isinstance(self.diagnostic, str) or not self.diagnostic:
            raise ValueError("source issue requires its operational diagnostic")


class APDocumentBridge:
    """A task's independent source views and conservative header consensus."""
    def __init__(self, doc_id: str, sources: Iterable[APSourceView], *,
                 source_issues: Iterable[APSourceIssue] = ()) -> None:
        if not isinstance(doc_id, str) or not doc_id:
            raise ValueError("canonical AP task ID is required")
        self.doc_id = doc_id
        self.sources = tuple(sources)
        self.source_issues = tuple(source_issues)
        if any(not isinstance(source, APSourceView) for source in self.sources):
            raise TypeError("AP task requires independent APSourceView attachments")
        if any(not isinstance(issue, APSourceIssue) for issue in self.source_issues):
            raise TypeError("AP task source issues require APSourceIssue")
        paths = [source.source_path for source in self.sources] + [issue.source_path for issue in self.source_issues]
        if len(set(paths)) != len(paths):
            raise ValueError("an AP attachment cannot be supplied twice")
        combined: dict[str, list[Fact]] = {}
        for source in self.sources:
            for name, candidates in source.facts.fields.items():
                if not name.startswith("line."):
                    combined.setdefault(name, []).extend(candidates)
        self.facts = APFactSet(combined)

    @classmethod
    def from_task_sources(cls, task) -> "APDocumentBridge":
        """Adapt the existing replay loader contract, retaining failures/unknowns."""
        from .documents.ap_sources import APTaskSources
        if not isinstance(task, APTaskSources):
            raise TypeError("expected the existing APTaskSources contract")
        views, issues = [], []
        for attachment in task.attachments:
            if attachment.error or attachment.normalized is None:
                issues.append(APSourceIssue(attachment.path, attachment.error or "NORMALIZATION_UNAVAILABLE",
                                             tuple(deepcopy(attachment.unknowns))))
                continue
            if attachment.document is not None and (
                    attachment.document.path != attachment.path
                    or attachment.document.source_sha256 != attachment.normalized.facts.source_sha256):
                raise ValueError("normalized AP attachment differs from its parsed original")
            if attachment.facts is not None and attachment.facts.to_dict() != attachment.normalized.raw.to_dict():
                raise ValueError("normalized AP attachment differs from its accepted raw facts")
            views.append(APSourceView.from_normalized(attachment.normalized, source_path=attachment.path,
                classification=attachment.classification, unknowns=attachment.unknowns))
        return cls(task.doc_id, views, source_issues=issues)

    def field(self, name: str, *, kind: str = "any") -> APField:
        if name.startswith("line."):
            return APField(name, "UNKNOWN", None, (), (), ("ATTACHMENT_SCOPE_REQUIRED",))
        return self.facts.field(name, kind=kind)

    @property
    def header(self) -> APHeaderFacts:
        return self.facts.header

    @property
    def lines(self) -> tuple[APLineFacts, ...]:
        """All observed rows with source identities; never concatenate for posting."""
        return tuple(line for source in self.sources for line in source.lines)

    @property
    def financial_sources(self) -> tuple[APSourceView, ...]:
        return tuple(source for source in self.sources if source.classification.status == "CLASSIFIED"
                     and source.classification.document_type in {"INVOICE", "CREDIT_NOTE", "DOWN_PAYMENT_REQUEST"})

    @property
    def notice_sources(self) -> tuple[APSourceView, ...]:
        return tuple(source for source in self.sources if source.classification.status == "CLASSIFIED"
                     and source.classification.document_type not in {"INVOICE", "CREDIT_NOTE", "DOWN_PAYMENT_REQUEST"})

    @property
    def unclassified_sources(self) -> tuple[APSourceView, ...]:
        return tuple(source for source in self.sources if source.classification.status != "CLASSIFIED")

    @property
    def classification(self) -> DocumentClassification:
        classifications = tuple(source.classification for source in self.sources)
        evidence = tuple(f for value in classifications for f in value.evidence)
        diagnostics = tuple(d for value in classifications for d in value.diagnostics)
        types = {value.document_type for value in classifications if value.status == "CLASSIFIED"}
        if any(value.status == "CONFLICT" for value in classifications) or len(types) > 1:
            status, document_type = "CONFLICT", None
        elif self.source_issues or not classifications or any(value.status == "UNKNOWN" for value in classifications):
            status, document_type = "UNKNOWN", None
        else:
            status, document_type = "CLASSIFIED", next(iter(types))
        return DocumentClassification(document_type, status, evidence, diagnostics, DOCUMENT_BRIDGE_VERSION)
