"""Resolve foreign advance counterparties from explicit document/PO/master facts.

No extraction, name similarity, inferred approval, journal repair or state writes.
An approval pair represents one evidenced approval statement supplied upstream.
"""
from collections.abc import Iterable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import re
from typing import Any

from .ap_identity import APIdentityResult, IdentityCatalog
from .ap_journal import ApprovedAdvanceOrder
from .facts import Evidence, Fact


@dataclass(frozen=True)
class AdvanceApproval:
    po_reference: Fact
    approved: Fact


@dataclass(frozen=True)
class AdvanceSourceResolution:
    status: str
    order: ApprovedAdvanceOrder | None
    vendor_master: Mapping[str, Any] | None
    evidence: tuple[Evidence, ...]
    diagnostics: tuple[str, ...] = ()
    identity: APIdentityResult | None = None


def resolve_advance_sources(*, company: str, currency: str, invoice_date: str,
                            po_reference: Fact | None, approval: AdvanceApproval | None,
                            purchase_orders: Iterable[Mapping[str, Any]],
                            vendors: Iterable[Mapping[str, Any]],
                            companies: Iterable[Mapping[str, Any]],
                            supplier_tax_ids: Sequence[Fact] | None = None,
                            recipient_tax_ids: Sequence[Fact] | None = None) -> AdvanceSourceResolution:
    """An evidenced exact PO determines its vendor; observed identities corroborate.

    A missing tax ID on a foreign advance request does not invent a vendor: the
    exact documentary PO, explicit approval and affiliated master are required.
    Observed conflicting/ambiguous identifiers cannot be ignored. The separate
    journal builder still requires posting eligibility, monetary inputs and FX.
    """
    if date.fromisoformat(invoice_date).isoformat() != invoice_date:
        raise ValueError("invoice date must be ISO")
    if not isinstance(currency, str) or not re.fullmatch("[A-Z]{3}", currency):
        raise ValueError("ISO document currency required")
    vendor_rows = deepcopy(tuple(vendors))
    company_rows = deepcopy(tuple(companies))
    catalogue = IdentityCatalog(vendors=vendor_rows, companies=company_rows)
    company_master = next((row for row in company_rows if row["code"] == company), None)
    if company_master is None:
        raise ValueError("company must exist in supplied master")
    evidence = []
    def unresolved(status, diagnostic, identity=None):
        return AdvanceSourceResolution(status, None, None, tuple(evidence), (diagnostic,), identity)
    if po_reference is None:
        return unresolved("UNKNOWN", "documentary PO reference unresolved")
    if not isinstance(po_reference, Fact):
        raise TypeError("documentary PO reference requires Fact/Evidence")
    evidence.append(po_reference.evidence)
    po_id = po_reference.value
    if po_id is None or (isinstance(po_id, str) and not po_id.strip()):
        return unresolved("UNKNOWN", "documentary PO reference missing")
    if not isinstance(po_id, str):
        raise TypeError("documentary PO reference must be text")
    orders = {}
    for row in deepcopy(tuple(purchase_orders)):
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in orders:
            raise ValueError("unique nonempty PO identity required")
        orders[identifier] = row
    po = orders.get(po_id)
    if po is None:
        return unresolved("NOT_FOUND", "documentary PO not found in phase")
    evidence.extend(Evidence("erp/purchase_orders.jsonl", f"id={po_id}.{field}")
                    for field in ("company", "currency", "vendor", "created_on"))
    if (po.get("company"), po.get("currency")) != (company, currency):
        return unresolved("CONFLICT", "PO company/currency differs from document scope")
    created = po.get("created_on")
    if not isinstance(created, str):
        return unresolved("UNKNOWN", "PO creation date unresolved")
    if date.fromisoformat(created).isoformat() != created:
        raise ValueError("PO creation date must be ISO")
    if created > invoice_date:
        return unresolved("CONFLICT", "PO originates after advance request")
    if approval is None:
        return unresolved("UNKNOWN", "explicit PO approval unresolved")
    if not isinstance(approval, AdvanceApproval) or not all(
            isinstance(fact, Fact) for fact in (approval.po_reference, approval.approved)):
        raise TypeError("approval requires an evidenced PO and approval fact")
    evidence.extend((approval.po_reference.evidence, approval.approved.evidence))
    if approval.po_reference.value != po_id:
        return unresolved("CONFLICT", "approval references another PO")
    if approval.po_reference.evidence.document != approval.approved.evidence.document:
        return unresolved("UNKNOWN", "approval facts do not identify one source statement")
    if approval.approved.value is not True:
        return unresolved("NOT_APPROVED" if approval.approved.value is False else "UNKNOWN",
                          "PO approval must be observed true")
    vendor = next((row for row in vendor_rows if row["id"] == po.get("vendor")), None)
    if vendor is None:
        return unresolved("NOT_FOUND", "PO vendor not found in phase master")
    evidence.extend(Evidence("erp/vendors.jsonl", f"id={vendor['id']}.{field}")
                    for field in ("country", "companies"))
    if "companies" not in vendor:
        return unresolved("UNKNOWN", "vendor company affiliation unresolved")
    if company not in vendor["companies"]:
        return unresolved("CONFLICT", "PO vendor not enabled for company")
    country, local_country = vendor.get("country"), company_master.get("country")
    if any(not isinstance(value, str) or not re.fullmatch("[A-Z]{2}", value) or value == "ZZ"
           for value in (country, local_country)):
        return unresolved("UNKNOWN", "vendor/company country unresolved")
    if country == local_country:
        return unresolved("DOMESTIC", "advance request policy requires foreign vendor")
    identity = catalogue.resolve(supplier_tax_ids=supplier_tax_ids,
                                 recipient_tax_ids=recipient_tax_ids, expected_company=company)
    evidence.extend((*identity.supplier.evidence, *identity.recipient.evidence,
                     Evidence("erp/companies.json", f"code={company}.country")))
    for match, expected, role in ((identity.supplier, vendor["id"], "supplier"),
                                  (identity.recipient, company, "recipient")):
        if match.status in {"UNKNOWN", "MISSING"}:
            continue  # Counterparty is independently proven by the approved documentary PO.
        if match.status != "RESOLVED" or match.identity != expected:
            return unresolved("CONFLICT", f"observed {role} identity contradicts or cannot corroborate PO", identity)
    reference = f"{approval.approved.evidence.document}#{approval.approved.evidence.field}"
    order = ApprovedAdvanceOrder(company, vendor["id"], currency, po_id, True, reference)
    return AdvanceSourceResolution("RESOLVED", order, deepcopy(vendor), tuple(evidence), identity=identity)
