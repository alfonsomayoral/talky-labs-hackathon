"""Bind one AP task's document facts and message metadata to the identity core.

Company precedence: the single company of the documentary PO(s) found in the
phase, else the recipient when the vendor is unknown or enabled for it, else the
vendor's single affiliation; otherwise unresolved. Vendor: exact tax ID; an exact sender domain
only when no tax ID was observed; a bounded semantic selection only among the
master candidates the core left ambiguous. No name similarity, no golden.
"""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .ap_identity import APIdentityResult, IdentityCatalog
from .documents.contracts import ResolutionResult
from .facts import DocumentFacts, Evidence, Fact


@dataclass(frozen=True)
class APIdentityBinding:
    company: str | None
    vendor_id: str | None
    identity: APIdentityResult
    diagnostics: tuple[str, ...]
    evidence: tuple[Evidence, ...]


def _fields(documents: Sequence[DocumentFacts]) -> dict[str, list[Fact]]:
    fields: dict[str, list[Fact]] = {}
    for document in documents:
        for key, facts in document.fields.items():
            fields.setdefault(key, []).extend(facts)
    return fields


def _domain(address: object) -> str | None:
    if not isinstance(address, str) or address.count("@") != 1:
        return None
    return address.rsplit("@", 1)[1].strip().lower() or None


def resolve_ap_identity(documents: Sequence[DocumentFacts], message: Mapping[str, Any], data,
                        semantic: ResolutionResult | None = None) -> APIdentityBinding:
    """``semantic`` is a resolver result for the supplier; it counts only when it selects
    exactly one ID among the core's ambiguous/conflicting master candidates."""
    catalog = IdentityCatalog.from_phase(data)
    fields = _fields(documents)
    supplier_facts = fields.get("supplier_tax_id", [])
    recipient_facts = fields.get("recipient_tax_id", [])
    first = catalog.resolve(supplier_tax_ids=supplier_facts, recipient_tax_ids=recipient_facts,
                            expected_company=None)
    supplier, recipient = first.supplier, first.recipient
    evidence = [*supplier.evidence, *recipient.evidence]
    diagnostics = [f"SUPPLIER_{supplier.status}", f"RECIPIENT_{recipient.status}"]

    vendor_id = supplier.identity
    if supplier.status in {"AMBIGUOUS", "CONFLICT"}:
        if (semantic is not None and semantic.status == "SELECTED" and len(semantic.selected_ids) == 1
                and semantic.selected_ids[0] in supplier.candidates):
            vendor_id = semantic.selected_ids[0]
            diagnostics.append("SUPPLIER_SEMANTIC_SELECTED")
        else:
            diagnostics.append("SUPPLIER_ABSTAINED")
    elif supplier.status in {"UNKNOWN", "MISSING"}:
        field = "from" if "from" in message else "uploaded_by"
        domain = _domain(message.get(field))
        matches = [row for row in data.table("vendors") if domain and _domain(row.get("email")) == domain]
        if len(matches) == 1:
            vendor_id = matches[0]["id"]
            diagnostics.append("SUPPLIER_SENDER_DOMAIN")
            evidence += [Evidence(f"inbox/ap/{message.get('doc_id')}/message.json", field, quote=message[field]),
                         Evidence("erp/vendors.jsonl", f"id={vendor_id}.email", quote=matches[0]["email"])]
    elif supplier.status == "NOT_FOUND":
        diagnostics.append("VENDOR_NOT_IN_MASTER")

    po_companies = {}
    for fact in (fact for key, facts in sorted(fields.items())
                 if key == "po_reference" or key.endswith(".po_reference") for fact in facts):
        try:
            po = data.get("purchase_orders", fact.value)
        except KeyError:
            continue
        po_companies.setdefault(po["company"], []).append(
            (fact.evidence, Evidence("erp/purchase_orders.jsonl", f"id={po['id']}.company")))
    affiliations = next((tuple(row.get("companies") or ()) for row in data.table("vendors")
                         if row["id"] == vendor_id), ())
    company = None
    if len(po_companies) == 1:
        company = next(iter(po_companies))
        evidence += [e for pair in po_companies[company] for e in pair]
        diagnostics.append("COMPANY_FROM_PO")
    elif len(po_companies) > 1:
        diagnostics.append("COMPANY_PO_CONFLICT")
    elif recipient.identity is not None and (not affiliations or recipient.identity in affiliations):
        company = recipient.identity
        diagnostics.append("COMPANY_FROM_RECIPIENT")
    elif len(affiliations) == 1:
        company = affiliations[0]
        evidence.append(Evidence("erp/vendors.jsonl", f"id={vendor_id}.companies"))
        diagnostics.append("COMPANY_FROM_VENDOR_AFFILIATION")
    else:
        diagnostics.append("COMPANY_UNRESOLVED")

    identity = catalog.resolve(supplier_tax_ids=supplier_facts, recipient_tax_ids=recipient_facts,
                               expected_company=company)
    if identity.wrong_addressee:
        diagnostics.append("WRONG_ADDRESSEE")
    return APIdentityBinding(company, vendor_id, identity, tuple(diagnostics), tuple(dict.fromkeys(evidence)))

