"""Exact AP supplier and recipient identity from evidenced facts and ERP masters.

No name similarity, extraction or decision inference. Missing, unknown and
contradictory identifiers stay distinct. Country prefixes are matched only when
the master supplies that VAT alias; a Mexican RFC is never blindly shortened.
"""
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from .facts import Evidence, Fact


@dataclass(frozen=True)
class IdentityMatch:
    status: str
    identity: str | None
    candidates: tuple[str, ...]
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class APIdentityResult:
    supplier: IdentityMatch
    recipient: IdentityMatch
    expected_company: str | None
    wrong_addressee: bool | None
    vendor_enabled_for_company: bool | None


def normalize_tax_identifier(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("tax identifier must be text")
    normalized = re.sub(r"[\s./-]", "", value.upper())
    if not normalized or not re.fullmatch(r"[A-Z0-9]+", normalized):
        raise ValueError("tax identifier must contain ASCII letters/digits")
    return normalized


class IdentityCatalog:
    """Snapshot of masters. Duplicate master IDs fail; shared tax IDs stay ambiguous."""

    def __init__(self, *, vendors: Iterable[Mapping[str, Any]],
                 companies: Iterable[Mapping[str, Any]],
                 vendor_source: str = "erp/vendors.jsonl",
                 company_source: str = "erp/companies.json") -> None:
        self._vendors, self._vendor_index = self._index(vendors, "id", vendor_source)
        self._companies, self._company_index = self._index(companies, "code", company_source)

    @staticmethod
    def _index(rows: Iterable[Mapping[str, Any]], id_field: str, source: str):
        records, index = {}, {}
        for source_row in rows:
            row = dict(source_row)
            identity = row[id_field]
            if not isinstance(identity, str) or not identity or identity in records:
                raise ValueError("unique nonempty master identity required")
            if "companies" in row:
                affiliations = row["companies"]
                if (not isinstance(affiliations, (list, tuple))
                        or any(not isinstance(c, str) or not c for c in affiliations)):
                    raise ValueError("vendor companies must be explicit company codes")
                row["companies"] = tuple(affiliations)
            records[identity] = row
            for field in ("tax_id", "vat_id"):
                value = row.get(field)
                if value is not None and value != "":
                    token = normalize_tax_identifier(value)
                    index.setdefault(token, {}).setdefault(identity, []).append(
                        Evidence(source, f"{id_field}={identity}.{field}", quote=value))
        return records, index

    @staticmethod
    def _match(facts: Sequence[Fact] | None, index) -> IdentityMatch:
        if facts is None:
            return IdentityMatch("UNKNOWN", None, (), ())
        facts = tuple(facts)
        if any(not isinstance(fact, Fact) for fact in facts):
            raise TypeError("identity facts require Fact/Evidence")
        evidence = tuple(f.evidence for f in facts)
        if not facts:
            return IdentityMatch("MISSING", None, (), evidence)
        tokens = set()
        for fact in facts:
            if fact.value is None or fact.value == "":
                tokens.add(None)
            else:
                tokens.add(normalize_tax_identifier(fact.value))
        if tokens == {None}:
            return IdentityMatch("MISSING", None, (), evidence)
        matches = [set(index.get(token, {})) for token in tokens if token is not None]
        candidates = set().union(*matches)
        common = set.intersection(*matches)
        if None in tokens or (len(tokens) > 1 and not common):
            return IdentityMatch("CONFLICT", None, tuple(sorted(candidates)), evidence)
        if not candidates:
            return IdentityMatch("NOT_FOUND", None, (), evidence)
        if len(common) != 1:
            return IdentityMatch("AMBIGUOUS", None, tuple(sorted(common)), evidence)
        identity = next(iter(common))
        master_evidence = tuple(e for token in sorted(tokens)
                                for e in index[token].get(identity, ()))
        return IdentityMatch("RESOLVED", identity, (identity,), (*evidence, *master_evidence))

    def resolve(self, *, supplier_tax_ids: Sequence[Fact] | None,
                recipient_tax_ids: Sequence[Fact] | None,
                expected_company: str | None) -> APIdentityResult:
        """Expected company comes explicitly from task/confirmed PO, never inbox guess.

        None facts mean extraction has not resolved the field; an empty list or
        evidenced None means it is absent. A known supplier's absent affiliation
        remains unknown rather than automatically authorizing every company.
        """
        if expected_company is not None and expected_company not in self._companies:
            raise ValueError("expected company must exist in supplied master")
        supplier = self._match(supplier_tax_ids, self._vendor_index)
        recipient = self._match(recipient_tax_ids, self._company_index)
        wrong = (recipient.identity != expected_company
                 if recipient.identity is not None and expected_company is not None else None)
        enabled = None
        if supplier.identity is not None and expected_company is not None:
            affiliations = self._vendors[supplier.identity].get("companies")
            if affiliations is not None:
                enabled = expected_company in affiliations
        return APIdentityResult(supplier, recipient, expected_company, wrong, enabled)

    @classmethod
    def from_phase(cls, data) -> "IdentityCatalog":
        """Read masters through M0 PhaseData, which excludes golden paths."""
        return cls(vendors=data.table("vendors"), companies=data.companies)
