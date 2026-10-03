"""Prepared AR observation contract and deterministic adapter (#56).

Inputs are independently normalized observations, not provider responses. The
shared extractor still needs an AR-specific schema/prompt and capture integration.
No provider, parser, cache, accounting calculation or posting is started here.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Any, NoReturn

from ..data import PhaseData
from ..documents.contracts import ParsedDocument, fingerprint
from ..facts import DocumentFacts, Evidence, Fact
from .inputs import (BillingFacts, CertificationFacts, Chapter, ExtraService,
                     PlantMwh, PlantSettlement, PpaFacts, RevisionFacts,
                     ServiceFacts, SettlementFacts)
from .model import BillingItem, BillingType


AR_OBSERVATIONS_VERSION = "ar-observations-v1"

# Units are explicit: normalization must preserve its original literal facts
# separately. Counts are parser/reviewer metadata, never model confidence.
_HEADERS = {
    BillingType.OBRA_CERTIFICATION: {
        "month", "cumulative_cents", "previous_cents", "current_cents", "status_text", "authority_text"},
    BillingType.SERVICE_MONTHLY: {"month", "canon_cents", "canon_status_text", "authority_text"},
    BillingType.PRICE_REVISION: {
        "old_fee_cents", "new_fee_cents", "effective_date", "approval_date",
        "status_text", "decree"},
    BillingType.PPA: {"period", "share_bp", "price_mwh_cents"},
    BillingType.MARKET_SETTLEMENT: {"period", "deviations_cents"},
}
_TABLES = {
    BillingType.OBRA_CERTIFICATION: ("chapter", {"number", "description", "amount_cents"}),
    BillingType.SERVICE_MONTHLY: ("extra", {"order", "description", "amount_cents", "status_text"}),
    BillingType.PRICE_REVISION: ("revision_month", {"month"}),
    BillingType.PPA: ("plant", {"reference", "mwh_milli"}),
    BillingType.MARKET_SETTLEMENT: ("plant", {"reference", "amount_cents", "mwh_milli"}),
}
_CONFIRMED = frozenset({
    "CONFORME", "CONFORMECONFORME", "APROBADA", "APROBADO", "APROVADA", "APROVADO",
    "RESUELVO: APROBAR LA REVISIÓN DE PRECIOS",
})
_PENDING = frozenset({"PENDIENTE DE APROBACIÓN", "PENDIENTE DE CONFORMIDAD", "NO FACTURAR"})
_AUTHORITIES = {
    BillingType.OBRA_CERTIFICATION: {"DIRECCIÓN FACULTATIVA", "DIRECCIÓN FACULTATIVA – INGENIERO",
                                    "DIRECCIÓN FACULTATIVA - INGENIERO",
                                    "DIRECCIÓN FACULTATIVA – ARQUITECTO",
                                    "DIRECCIÓN FACULTATIVA - ARQUITECTO"},
    BillingType.SERVICE_MONTHLY: {"TÉCNICO MUNICIPAL"},
}


@dataclass(frozen=True, slots=True)
class BillingObservations:
    """One attachment's AR observations; PDF and item.json stay independent.

    ``row_counts`` declares complete tables as established by a parser or source
    reviewer. Zero extras must be explicit. Original-source evaluation must still
    establish table completeness; a reported count alone does not prove it.
    ``DocumentFacts`` retains all candidates/evidence and its shared JSON codec.
    """
    type: BillingType
    facts: DocumentFacts
    row_counts: dict[str, int]
    schema_version: str = AR_OBSERVATIONS_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AR_OBSERVATIONS_VERSION:
            raise ValueError("unsupported AR observation schema")
        if not isinstance(self.type, BillingType) or not isinstance(self.facts, DocumentFacts):
            raise ValueError("AR observations require a billing type and DocumentFacts")
        if (not isinstance(self.row_counts, dict)
                or any(not isinstance(k, str) or type(v) is not int or v < 0
                       for k, v in self.row_counts.items())):
            raise ValueError("table counts require names and nonnegative integers")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "type": self.type.value,
                "facts": self.facts.to_dict(), "row_counts": dict(self.row_counts)}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "BillingObservations":
        if set(value) != {"schema_version", "type", "facts", "row_counts"}:
            raise ValueError("unexpected AR observation envelope fields")
        return cls(BillingType(value["type"]), DocumentFacts.from_dict(value["facts"]),
                   value["row_counts"], value["schema_version"])


@dataclass(frozen=True, slots=True)
class BillingObservationDiagnostic:
    code: str
    field: str
    message: str
    candidates: tuple[Fact, ...] = ()


@dataclass(frozen=True, slots=True)
class BillingAdaptation:
    observations: BillingObservations
    facts: BillingFacts | None
    diagnostics: tuple[BillingObservationDiagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class BillingSourcesAdaptation:
    """Keep every attachment's identity when combining compatible observations."""
    attachments: tuple[tuple[BillingObservations, ParsedDocument], ...]
    facts: BillingFacts | None
    diagnostics: tuple[BillingObservationDiagnostic, ...] = ()


class _Unresolved(Exception):
    def __init__(self, code: str, field: str, message: str,
                 candidates: tuple[Fact, ...] = ()) -> None:
        self.diagnostic = BillingObservationDiagnostic(code, field, message, candidates)


def _text(value: str) -> str:
    return " ".join(value.split())


class _Reader:
    def __init__(self, observations: BillingObservations) -> None:
        self.observations = observations
        self.fields = observations.facts.fields
        self.evidence: list[Evidence] = []

    def one(self, field: str) -> object:
        candidates = tuple(self.fields.get(field, ()))
        if not candidates:
            raise _Unresolved("MISSING", field, "required observation is absent")
        first = candidates[0].value
        if any(type(f.value) is not type(first) or f.value != first for f in candidates[1:]):
            raise _Unresolved("CONFLICT", field, "observations disagree; no candidate selected", candidates)
        if first is None:
            raise _Unresolved("MISSING", field, "explicit absence cannot supply a required value", candidates)
        self.evidence.extend(f.evidence for f in candidates)
        return first

    def invalid(self, field: str, message: str) -> NoReturn:
        raise _Unresolved("INVALID", field, message, tuple(self.fields.get(field, ())))

    def string(self, field: str) -> str:
        value = self.one(field)
        if not isinstance(value, str) or not value.strip():
            self.invalid(field, "expected a nonempty source string")
        return value.strip()

    def integer(self, field: str, *, signed: bool = False) -> int:
        value = self.one(field)
        if type(value) is not int or (not signed and value < 0):
            self.invalid(field, "expected an integer in the declared units; floats/bools are invalid")
        return value

    def month(self, field: str) -> str:
        value = self.string(field)
        if not re.fullmatch(r"[0-9]{4}-(?:0[1-9]|1[0-2])", value):
            self.invalid(field, "expected YYYY-MM")
        try:
            date.fromisoformat(value + "-01")
        except ValueError:
            self.invalid(field, "invalid calendar month")
        return value

    def day(self, field: str) -> str:
        value = self.string(field)
        try:
            if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
                raise ValueError()
            date.fromisoformat(value)
        except ValueError:
            self.invalid(field, "expected a valid ISO calendar date")
        return value

    def status(self, field: str) -> bool:
        value = _text(self.string(field)).upper()
        if value in _CONFIRMED:
            return True
        if value in _PENDING:
            return False
        raise _Unresolved("UNKNOWN_STATUS", field, "status text needs an explicit lexical rule",
                          tuple(self.fields[field]))

    def authority(self) -> None:
        value = _text(self.string("authority_text")).upper()
        if value not in _AUTHORITIES[self.observations.type]:
            raise _Unresolved("UNKNOWN_AUTHORITY", "authority_text", "observed signer role needs an explicit rule",
                              tuple(self.fields["authority_text"]))

    def rows(self) -> range:
        stem, allowed = _TABLES[self.observations.type]
        if set(self.observations.row_counts) != {stem}:
            raise _Unresolved("MISSING_TABLE_COVERAGE", stem, "declare exactly this complete table's row count")
        count = self.observations.row_counts[stem]
        if count == 0 and stem != "extra":
            raise _Unresolved("INVALID_TABLE", stem, "this document requires at least one table row")
        found = set()
        for field in self.fields:
            if field in _HEADERS[self.observations.type] or field in {"contract_reference", "currency"}:
                continue
            match = re.fullmatch(rf"{stem}\.([1-9][0-9]*)\.(.+)", field)
            if not match or match[2] not in allowed:
                raise _Unresolved("UNSUPPORTED_FIELD", field, "field is outside the versioned AR contract")
            found.add(int(match[1]))
        if (len(found) != count or (count and (min(found) != 1 or max(found) != count))):
            raise _Unresolved("INCOMPLETE_TABLE", stem, "row identities differ from declared coverage")
        return range(1, count + 1)

    def proof(self) -> tuple[Evidence, ...]:
        return tuple(dict.fromkeys(self.evidence))


def _check_source(item: BillingItem, observations: BillingObservations,
                  document: ParsedDocument) -> None:
    if observations.type is not item.type:
        raise _Unresolved("TYPE_MISMATCH", "type", "observed type differs from item metadata")
    if (observations.facts.source_sha256 != document.source_sha256
            or not document.path.startswith(f"inbox/ar/billing/{item.id}/")):
        raise _Unresolved("SOURCE_MISMATCH", "", "attachment hash/path differs from this billing item")
    for field, candidates in observations.facts.fields.items():
        for fact in candidates:
            evidence = fact.evidence
            matches = [b for b in document.blocks if evidence.field in (b.id, b.source_field)
                       and evidence.page == b.page]
            if (evidence.document != document.path or not evidence.quote or not _text(evidence.quote)
                    or not any(_text(evidence.quote) in _text(b.text) for b in matches)):
                raise _Unresolved("UNSUPPORTED_EVIDENCE", field,
                                  "normalized observations require a located original text quotation", (fact,))


def _plant(data: PhaseData, item: BillingItem, reader: _Reader, field: str,
           document: ParsedDocument, references=None) -> str:
    """Exact printed name/id against the active company and contract; no ranking."""
    reference = reader.string(field)
    contract = data.get("sales_contracts", item.contract)
    if contract["company"] != item.company or contract["customer"] != item.customer:
        raise _Unresolved("CONTRACT_MISMATCH", field, "contract company/customer differ from item metadata")
    allowed = set(contract.get("plants", ()))
    matches = [row["id"] for row in data.find("cost_centers", company=item.company)
               if row["id"] in allowed and reference in (row["id"], row["desc"])]
    if len(matches) != 1:
        if references is not None:
            resolved = references.plant_id(field, reference, reader.observations, document,
                                           data=data, item=item)
            if resolved is not None:
                return resolved
        raise _Unresolved("UNRESOLVED_PLANT", field, "printed reference has no unique exact master match",
                          tuple(reader.fields[field]))
    return matches[0]


def adapt_billing_observations(data: PhaseData, item: BillingItem,
                              observations: BillingObservations,
                              document: ParsedDocument, *, references=None) -> BillingAdaptation:
    """Return typed engine inputs or a source-traced diagnostic, never an invoice.

    Absence/unknown approval does not become pending approval. Contradictions stay
    in ``observations`` and diagnostics; neither item.json nor ERP replaces them.
    Text evidence verifies location, not the correctness of prior normalization
    or row completeness. Image-only observations await reviewed image support.
    """
    return _adapt(data, item, observations, document, references=references)


def _adapt(data, item, observations, document, *, references=None, checked=False):
    reader = _Reader(observations)
    try:
        if references is not None and getattr(references, "diagnostics", ()):
            return BillingAdaptation(observations, None, references.diagnostics)
        if not checked:
            _check_source(item, observations, document)
        rows = reader.rows()
        if reader.string("currency") != data.get("companies", item.company)["currency"]:
            raise _Unresolved("CURRENCY_MISMATCH", "currency", "document currency differs from company local currency",
                              tuple(reader.fields["currency"]))
        if "contract_reference" in reader.fields:
            reference = reader.string("contract_reference")
            resolved = (references.reference_id("contract_reference", reference, observations,
                                               document, data=data, item=item)
                        if references is not None and reference != item.contract else None)
            if reference != item.contract and resolved != item.contract:
                raise _Unresolved("CONTRACT_MISMATCH", "contract_reference", "document and item references differ",
                                  tuple(reader.fields["contract_reference"]))
        facts: BillingFacts
        if item.type is BillingType.OBRA_CERTIFICATION:
            reader.authority()
            chapters = tuple(Chapter(reader.integer(f"chapter.{i}.number"),
                                     reader.string(f"chapter.{i}.description"),
                                     reader.integer(f"chapter.{i}.amount_cents")) for i in rows)
            if [c.number for c in chapters] != list(rows):
                raise _Unresolved("INVALID_CHAPTERS", "chapter", "chapter numbers must match their one-based rows")
            facts = CertificationFacts(reader.month("month"), chapters,
                                       reader.integer("cumulative_cents"), reader.integer("previous_cents"),
                                       reader.integer("current_cents"), reader.status("status_text"), reader.proof())
        elif item.type is BillingType.SERVICE_MONTHLY:
            reader.authority()
            if not reader.status("canon_status_text"):
                raise _Unresolved("UNCONFIRMED_SERVICE", "canon_status_text", "monthly service is not confirmed",
                                  tuple(reader.fields["canon_status_text"]))
            extras = tuple(ExtraService(reader.string(f"extra.{i}.order"),
                                        reader.string(f"extra.{i}.description"),
                                        reader.integer(f"extra.{i}.amount_cents"),
                                        reader.status(f"extra.{i}.status_text")) for i in rows)
            facts = ServiceFacts(reader.month("month"), reader.integer("canon_cents"), extras, reader.proof())
        elif item.type is BillingType.PRICE_REVISION:
            if not reader.status("status_text"):
                raise _Unresolved("UNCONFIRMED_REVISION", "status_text", "decree has no confirmed approval",
                                  tuple(reader.fields["status_text"]))
            months = tuple(reader.month(f"revision_month.{i}.month") for i in rows)
            if len(set(months)) != len(months):
                raise _Unresolved("DUPLICATE_MONTH", "revision_month", "decree months must be unique")
            decree = reader.string("decree") if "decree" in reader.fields else ""
            facts = RevisionFacts(reader.integer("old_fee_cents"), reader.integer("new_fee_cents"),
                                  reader.day("effective_date"), reader.day("approval_date"),
                                  months, decree, reader.proof())
        elif item.type is BillingType.PPA:
            plants = tuple(PlantMwh(_plant(data, item, reader, f"plant.{i}.reference", document, references),
                                   reader.integer(f"plant.{i}.mwh_milli")) for i in rows)
            share = reader.integer("share_bp")
            if share > 10000:
                reader.invalid("share_bp", "production share exceeds 100 percent")
            raw_price = reader.one("price_mwh_cents")
            if not isinstance(raw_price, (str, Decimal)):
                reader.invalid("price_mwh_cents", "expected exact Decimal or decimal string in cents/MWh")
            try:
                price = Decimal(raw_price)
            except InvalidOperation:
                reader.invalid("price_mwh_cents", "invalid decimal price")
            if not price.is_finite() or price < 0:
                reader.invalid("price_mwh_cents", "price must be finite and nonnegative")
            facts = PpaFacts(reader.month("period"), plants, share, price, reader.proof())
        else:
            plants = tuple(PlantSettlement(_plant(data, item, reader, f"plant.{i}.reference", document, references),
                                           reader.integer(f"plant.{i}.amount_cents"),
                                           reader.integer(f"plant.{i}.mwh_milli")
                                           if f"plant.{i}.mwh_milli" in reader.fields else None) for i in rows)
            facts = SettlementFacts(reader.month("period"), plants,
                                    reader.integer("deviations_cents", signed=True), reader.proof())
        if isinstance(facts, (PpaFacts, SettlementFacts)) and len({p.plant for p in facts.plants}) != len(facts.plants):
            raise _Unresolved("DUPLICATE_PLANT", "plant", "a plant cannot appear twice in the complete table")
        return BillingAdaptation(observations, facts)
    except _Unresolved as error:
        return BillingAdaptation(observations, None, (error.diagnostic,))
    except (KeyError, ValueError, TypeError) as error:
        diagnostic = BillingObservationDiagnostic("INVALID_INPUT", "", str(error))
        return BillingAdaptation(observations, None, (diagnostic,))


def adapt_billing_sources(data: PhaseData, item: BillingItem,
                         attachments: tuple[tuple[BillingObservations, ParsedDocument], ...], *,
                         references=()) -> BillingSourcesAdaptation:
    """Combine complementary facts after checking each original independently.

    Contradictory candidates remain visible. Tables with different coverage are
    unresolved; rows are never silently appended or renumbered across files.
    The composite envelope is internal and is never stored as an original fact.
    """
    attachments = tuple(attachments)
    try:
        if not attachments:
            raise _Unresolved("MISSING_SOURCE", "", "no original billing attachment supplied")
        if references and len(references) != len(attachments):
            raise _Unresolved("INVALID_INPUT", "", "references must correspond to every attachment")
        for bound in references:
            if bound is not None and bound.diagnostics:
                return BillingSourcesAdaptation(attachments, None, bound.diagnostics)
        fields: dict[str, list[Fact]] = {}
        counts: dict[str, int] = {}
        for observations, document in attachments:
            _check_source(item, observations, document)
            for name, count in observations.row_counts.items():
                if name in counts and counts[name] != count:
                    raise _Unresolved("CONFLICTING_TABLE_COVERAGE", name,
                                      "attachments disagree on complete table coverage")
                counts[name] = count
            for name, candidates in observations.facts.fields.items():
                fields.setdefault(name, []).extend(candidates)
        composite = BillingObservations(item.type, DocumentFacts(
            fingerprint([o.facts.to_dict() for o, _ in attachments]),
            AR_OBSERVATIONS_VERSION + ":combined", fields), counts)

        class SourceReferences:
            def _id(self, method, field, reference, *, data, item):
                selected = []
                for (observed, source), bound in zip(attachments, references):
                    if bound is None or field not in observed.facts.fields:
                        continue
                    value = getattr(bound, method)(field, reference, observed, source, data=data, item=item)
                    if value is not None:
                        selected.append(value)
                return selected[0] if selected and len(set(selected)) == 1 else None

            def plant_id(self, field, reference, observations, document, *, data, item):
                return self._id("plant_id", field, reference, data=data, item=item)

            def reference_id(self, field, reference, observations, document, *, data, item):
                return self._id("reference_id", field, reference, data=data, item=item)

        adapted = _adapt(data, item, composite, attachments[0][1],
                         references=SourceReferences() if references else None, checked=True)
        return BillingSourcesAdaptation(attachments, adapted.facts, adapted.diagnostics)
    except _Unresolved as error:
        return BillingSourcesAdaptation(attachments, None, (error.diagnostic,))
    except (KeyError, ValueError, TypeError) as error:
        return BillingSourcesAdaptation(attachments, None,
            (BillingObservationDiagnostic("INVALID_INPUT", "", str(error)),))
