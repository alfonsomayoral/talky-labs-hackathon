"""Source-bound AR master references: exact matches, then bounded semantics.

This boundary selects existing identities only. Item metadata remains authoritative
for company/customer/contract; semantic selections cannot replace it or accounting
fields. The shared resolver can be injected as a recorded/replayed boundary.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re

from ..data import PhaseData
from ..documents.contracts import (Candidate, ParsedDocument, ResolutionRequest,
                                   SemanticResolver, fingerprint)
from ..documents.replay import validate_resolution
from ..facts import DocumentFacts, Fact
from .model import BillingItem, BillingType
from .observations import (BillingObservationDiagnostic, BillingObservations,
                           _Unresolved, _check_source)


AR_RESOLUTION_VERSION = "ar-resolution-v1"
_KINDS = {BillingType.OBRA_CERTIFICATION: "obra_cert",
          BillingType.SERVICE_MONTHLY: "service_monthly",
          BillingType.PRICE_REVISION: "service_monthly",
          BillingType.PPA: "ppa", BillingType.MARKET_SETTLEMENT: "market"}


def _masters_sha256(data: PhaseData) -> str:
    return fingerprint({name: data.table(name)
                        for name in ("sales_contracts", "customers", "cost_centers")})


def _metadata(data: PhaseData, item: BillingItem) -> dict:
    contract = data.get("sales_contracts", item.contract)
    data.get("customers", item.customer)
    if contract.get("company") != item.company or contract.get("customer") != item.customer:
        raise ValueError("contract company/customer differ from item metadata")
    if "kind" in contract and contract["kind"] != _KINDS[item.type]:
        raise ValueError("contract kind differs from billing item type")
    return contract


def _eligible_contracts(data: PhaseData, item: BillingItem) -> list[dict]:
    _metadata(data, item)
    return [row for row in data.find("sales_contracts", company=item.company, customer=item.customer)
            if "kind" not in row or row["kind"] == _KINDS[item.type]]


def _request(item: BillingItem, document: ParsedDocument, candidates: list[Candidate],
             field: str, reference: str | None, entity: str, max_candidates: int) -> ResolutionRequest:
    if type(max_candidates) is not int or max_candidates < 1:
        raise ValueError("candidate limit must be a positive integer")
    if not document.path.startswith(f"inbox/ar/billing/{item.id}/"):
        raise ValueError("resolution source does not belong to this billing item")
    if len(candidates) > max_candidates:
        raise ValueError("eligible master candidate set exceeds configured limit")
    if reference is not None and (not isinstance(reference, str) or not reference.strip()):
        raise ValueError("printed reference must be nonempty text or absent")
    return ResolutionRequest(document, tuple(sorted(candidates, key=lambda candidate: candidate.id)),
                             {"workflow": AR_RESOLUTION_VERSION, "billing_item": item.id,
                              "entity": entity, "field": field, "reference": reference,
                              "expected_contract": item.contract, "expected_customer": item.customer,
                              "hard_constraints": {"company": item.company, "customer": item.customer},
                              "max_selections": 1,
                              "instruction": "Select only an evidenced existing identity for this printed reference; "
                                             "abstain when source evidence does not distinguish candidates."})


def billing_contract_request(data: PhaseData, item: BillingItem, document: ParsedDocument, *,
                             field: str = "contract_reference", reference: str | None = None,
                             max_candidates: int = 100) -> ResolutionRequest:
    """Existing contracts of the exact company/customer and billing kind only."""
    rows = _eligible_contracts(data, item)
    candidates = [Candidate(row["id"], {key: row[key] for key in
                  ("id", "name", "company", "customer", "kind", "project", "cc") if key in row})
                  for row in rows]
    return _request(item, document, candidates, field, reference, "contract", max_candidates)


def billing_customer_request(data: PhaseData, item: BillingItem, document: ParsedDocument, *,
                             field: str = "customer_name", reference: str | None = None,
                             max_candidates: int = 100) -> ResolutionRequest:
    """The customer eligible for the exact metadata contract; no inferred affiliation."""
    _metadata(data, item)
    customer = data.get("customers", item.customer)
    attributes = {key: customer[key] for key in ("id", "name", "tax_id", "country") if key in customer}
    attributes.update(company=item.company, customer=item.customer, contract=item.contract)
    return _request(item, document, [Candidate(item.customer, attributes)], field, reference,
                    "customer", max_candidates)


def billing_plant_request(data: PhaseData, item: BillingItem, document: ParsedDocument, *,
                          field: str, reference: str | None = None,
                          max_candidates: int = 100) -> ResolutionRequest:
    """Cost centers of this company that belong to the verified contract's plants."""
    contract = _metadata(data, item)
    allowed = set(contract.get("plants", ()))
    candidates = [Candidate(row["id"], {"id": row["id"], "name": row["desc"], "desc": row["desc"],
                                      "company": item.company, "customer": item.customer,
                                      "contract": item.contract})
                  for row in data.find("cost_centers", company=item.company) if row["id"] in allowed]
    request = _request(item, document, candidates, field, reference, "plant", max_candidates)
    request.context["hard_constraints"]["contract"] = item.contract
    return request


@dataclass(frozen=True, slots=True)
class ReferenceResolution:
    field: str
    reference: str | None
    status: str
    method: str
    selected_id: str | None
    candidate_ids: tuple[str, ...]
    request_sha256: str
    reason: str
    # Serialized proofs keep the frozen binding immutable; readers get copies.
    evidence_json: str = "[]"

    @property
    def evidence(self) -> tuple[dict, ...]:
        return tuple(json.loads(self.evidence_json))

    def to_dict(self) -> dict:
        return {"field": self.field, "reference": self.reference, "status": self.status,
                "method": self.method, "selected_id": self.selected_id,
                "candidate_ids": list(self.candidate_ids), "request_sha256": self.request_sha256,
                "reason": self.reason, "evidence": list(self.evidence)}


@dataclass(frozen=True, slots=True)
class BillingReferences:
    item_sha256: str
    source_sha256: str
    transformation_sha256: str
    observations_sha256: str
    masters_sha256: str
    references: tuple[ReferenceResolution, ...] = ()
    diagnostics: tuple[BillingObservationDiagnostic, ...] = ()

    def reference_id(self, field: str, reference: str, observations: BillingObservations,
                     document: ParsedDocument, *, data: PhaseData | None = None,
                     item: BillingItem | None = None) -> str:
        if (document.source_sha256 != self.source_sha256
                or document.transformation_sha256 != self.transformation_sha256
                or fingerprint(observations.to_dict()) != self.observations_sha256
                or item is not None and fingerprint(asdict(item)) != self.item_sha256
                or data is not None and _masters_sha256(data) != self.masters_sha256):
            raise ValueError("reference binding differs from the current source/item/masters")
        if self.diagnostics:
            raise ValueError("unresolved reference diagnostics prohibit applying bindings")
        matches = [binding for binding in self.references if binding.field == field]
        if (len(matches) != 1 or matches[0].reference != reference
                or matches[0].status != "SELECTED" or matches[0].selected_id is None):
            raise ValueError("printed reference has no selected source-bound identity")
        return matches[0].selected_id

    def plant_id(self, field: str, reference: str, observations: BillingObservations,
                 document: ParsedDocument, *, data: PhaseData | None = None,
                 item: BillingItem | None = None) -> str:
        if not re.fullmatch(r"plant\.[1-9][0-9]*\.reference", field):
            raise ValueError("plant binding requires a plant reference field")
        return self.reference_id(field, reference, observations, document, data=data, item=item)

    def to_dict(self) -> dict:
        return {"schema_version": AR_RESOLUTION_VERSION, "item_sha256": self.item_sha256,
                "source_sha256": self.source_sha256, "transformation_sha256": self.transformation_sha256,
                "observations_sha256": self.observations_sha256, "masters_sha256": self.masters_sha256,
                "references": [reference.to_dict() for reference in self.references],
                "diagnostics": [asdict(diagnostic) for diagnostic in self.diagnostics]}


def _observed(field: str, facts: tuple[Fact, ...]) -> str | None:
    if not facts:
        return None
    values = {fingerprint(fact.value) for fact in facts}
    if len(values) != 1:
        raise _Unresolved("CONFLICT", field, "printed reference observations disagree", facts)
    value = facts[0].value
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _Unresolved("INVALID_REFERENCE", field, "printed reference must be nonempty source text", facts)
    return value.strip()


def _global_exact_ids(data: PhaseData, entity: str, reference: str) -> set[str]:
    table = {"contract": "sales_contracts", "customer": "customers", "plant": "cost_centers"}[entity]
    name_key = "desc" if entity == "plant" else "name"
    token = " ".join(reference.split()).casefold()
    return {row["id"] for row in data.find(table)
            if reference == row["id"]
            or isinstance(row.get(name_key), str) and " ".join(row[name_key].split()).casefold() == token}


async def _resolve(request: ResolutionRequest, facts: tuple[Fact, ...], resolver: SemanticResolver | None,
                   data: PhaseData, expected_id: str | None) -> ReferenceResolution:
    reference = request.context["reference"]
    entity, field = request.context["entity"], request.context["field"]
    candidates = tuple(candidate.id for candidate in request.candidates)
    evidence = [{"kind": "observed_reference", **asdict(fact.evidence), "value": fact.value} for fact in facts]
    matches = _global_exact_ids(data, entity, reference) if reference is not None else set()
    eligible = matches & set(candidates)
    reason, selected, status, method = "", None, "NO_MATCH", "EXACT"
    if matches and not eligible:
        reason = "exact printed identity lies outside the company/customer/contract eligibility scope"
    elif len(eligible) == 1:
        selected, status = next(iter(eligible)), "SELECTED"
        reason = "unique exact printed ID/name in eligible masters"
        evidence.append({"kind": "master_match", "candidate_id": selected,
                         "attributes": next(candidate.attributes for candidate in request.candidates
                                            if candidate.id == selected)})
    elif resolver is None:
        status = "AMBIGUOUS" if eligible or len(candidates) > 1 else "NO_MATCH"
        reason = "printed reference has no unique exact match; no semantic resolver supplied"
    elif not candidates:
        reason = "there are no eligible master candidates"
    else:
        method = "SEMANTIC"
        request_sha256 = request.sha256
        result = await resolver.resolve(request)
        if request.sha256 != request_sha256:
            raise ValueError("resolution request changed while resolving")
        validate_resolution(request, result)
        if len(result.selected_ids) > 1 or not result.reason.strip():
            raise ValueError("AR resolution requires at most one selected identity and an explicit reason")
        if result.selected_ids and facts:
            def related(proof: dict) -> bool:
                quote = " ".join(str(proof.get("quote", "")).split())
                source_value = " ".join(str(proof.get("source_value", "")).split())
                printed = " ".join(reference.split())
                if not source_value or source_value not in printed or printed not in quote:
                    return False
                return any(proof.get("block_id") == fact.evidence.field
                           or any(block.id == proof.get("block_id")
                                  and block.source_field == fact.evidence.field
                                  and block.page == fact.evidence.page for block in request.document.blocks)
                           or fact.evidence.field == "image:" + str(proof.get("image_sha256", ""))
                           for fact in facts)
            if not any(related(proof) for proof in result.evidence):
                raise ValueError("semantic selection lacks proof tied to this printed reference")
        selected = result.selected_ids[0] if result.selected_ids else None
        status, reason = result.status, result.reason
        evidence.extend(result.evidence)
    if selected is not None and expected_id is not None and selected != expected_id:
        status, reason, selected = "CONFLICT", "document identity differs from exact item metadata", None
    return ReferenceResolution(field, reference, status, method, selected, candidates, request.sha256,
                               reason, json.dumps(evidence, ensure_ascii=False, sort_keys=True))


async def resolve_billing_references(data: PhaseData, item: BillingItem,
                                     observations: BillingObservations, document: ParsedDocument, *,
                                     resolver: SemanticResolver | None = None,
                                     raw_facts: DocumentFacts | None = None,
                                     max_candidates: int = 100) -> BillingReferences:
    """Cross-check observed identities and resolve plant names without rewriting facts.

    Metadata identities are validated exactly. Absent document contract/customer
    names do not establish an inferred match. Conflicting observations are rejected
    before resolver calls; a lone eligible master still needs printed source proof.
    Operational resolver failures propagate to the caller's recorder/runner.
    """
    references: list[ReferenceResolution] = []
    diagnostics: list[BillingObservationDiagnostic] = []
    masters_sha256 = _masters_sha256(data)
    observations_sha256 = fingerprint(observations.to_dict())
    raw_sha256 = fingerprint(raw_facts.to_dict()) if raw_facts is not None else None
    try:
        _metadata(data, item)
        _check_source(item, observations, document)
        if raw_facts is not None:
            _check_source(item, BillingObservations(item.type, raw_facts, observations.row_counts), document)
        fields = {name: tuple(values) for name, values in observations.facts.fields.items()
                  if name == "contract_reference" or re.fullmatch(r"plant\.[1-9][0-9]*\.reference", name)}
        if raw_facts is not None:
            for name in ("contract_reference", "contract_name", "customer_name"):
                if name in raw_facts.fields:
                    fields[name] = (*fields.get(name, ()), *raw_facts.fields[name])
        # Preflight all conflicts before any semantic work, including later rows.
        observed = {field: _observed(field, facts) for field, facts in fields.items()}
        for field in sorted(fields):
            reference = observed[field]
            if reference is None:
                if field.startswith("plant."):
                    raise _Unresolved("MISSING", field, "plant reference is explicitly absent", fields[field])
                continue
            if field in {"contract_reference", "contract_name"}:
                request = billing_contract_request(data, item, document, field=field, reference=reference,
                                                    max_candidates=max_candidates)
                expected_id = item.contract
            elif field == "customer_name":
                request = billing_customer_request(data, item, document, field=field, reference=reference,
                                                    max_candidates=max_candidates)
                expected_id = item.customer
            else:
                request = billing_plant_request(data, item, document, field=field, reference=reference,
                                                 max_candidates=max_candidates)
                expected_id = None
            result = await _resolve(request, fields[field], resolver, data, expected_id)
            references.append(result)
            if result.status != "SELECTED":
                diagnostics.append(BillingObservationDiagnostic("REFERENCE_" + result.status, field,
                                                                  result.reason, fields[field]))
                break
        selected_plants = [reference.selected_id for reference in references
                           if reference.field.startswith("plant.") and reference.selected_id is not None]
        if len(selected_plants) != len(set(selected_plants)):
            diagnostics.append(BillingObservationDiagnostic("DUPLICATE_PLANT", "plant",
                                                              "multiple source rows resolve to the same plant"))
        if _masters_sha256(data) != masters_sha256:
            raise ValueError("active master data changed during resolution")
        if (fingerprint(observations.to_dict()) != observations_sha256
                or raw_facts is not None and fingerprint(raw_facts.to_dict()) != raw_sha256):
            raise ValueError("source observations changed during resolution")
    except _Unresolved as error:
        diagnostics.append(error.diagnostic)
    except (KeyError, ValueError, TypeError) as error:
        diagnostics.append(BillingObservationDiagnostic("INVALID_REFERENCE_INPUT", "", str(error)))
    return BillingReferences(fingerprint(asdict(item)), document.source_sha256, document.transformation_sha256,
                             observations_sha256, masters_sha256,
                             tuple(references), tuple(diagnostics))
