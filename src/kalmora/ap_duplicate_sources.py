"""Bind the month's normalized documents and ERP history to the duplicate engine (#47).

No extraction, golden data, name similarity or vendor-currency defaults. A field
is bound only when every candidate of the invoice-typed attachments agrees.
"""
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any

from .ap_duplicates import duplicate_result, registered_duplicate_records
from .ap_identity import IdentityCatalog
from .data import PhaseData
from .facts import DocumentFacts, Evidence
from .model.ap_duplicate_record import DuplicateRecord
from .model.ap_duplicate_result import DuplicateResult

INVOICE_TYPES = frozenset(("INVOICE", "CREDIT_NOTE", "DOWN_PAYMENT_REQUEST"))


@dataclass(frozen=True)
class MonthDocument:
    doc_id: str
    message: Mapping[str, Any]
    # Normalized attachment facts with their classified type (None when unknown).
    attachments: tuple[tuple[DocumentFacts, str | None], ...]


def _agreed(sources: Sequence[DocumentFacts], name: str):
    facts = [fact for source in sources for fact in source.fields.get(name, ())]
    values = {fact.value for fact in facts}
    if len(values) != 1 or None in values:
        return None, ()
    return values.pop(), tuple(fact.evidence for fact in facts)


def month_record(document: MonthDocument, catalog: IdentityCatalog) -> tuple[str | None, DuplicateRecord | None]:
    """Return the agreed document type and its observation, or None if not bindable."""
    types = {kind for _, kind in document.attachments if kind is not None}
    if len(types) != 1:
        return None, None
    kind = types.pop()
    if kind not in INVOICE_TYPES:
        return kind, None
    sources = [facts for facts, attachment_type in document.attachments if attachment_type == kind]
    number, number_proof = _agreed(sources, "document_number")
    currency, _ = _agreed(sources, "currency")
    gross, amount_proof = _agreed(sources, "gross_cents")
    if gross is None:
        net, net_proof = _agreed(sources, "net_cents")
        tax, tax_proof = _agreed(sources, "tax_cents")
        if net is not None and tax is not None:
            gross, amount_proof = net + tax, (*net_proof, *tax_proof)
    start, _ = _agreed(sources, "period_start")
    end, _ = _agreed(sources, "period_end")
    def facts(name):
        return [fact for source in sources for fact in source.fields.get(name, ())]
    identity = catalog.resolve(supplier_tax_ids=facts("supplier_tax_id"),
                               recipient_tax_ids=facts("recipient_tax_id"), expected_company=None)
    received = document.message.get("received_at")
    if (identity.supplier.status != "RESOLVED" or identity.recipient.status != "RESOLVED"
            or not isinstance(number, str) or not isinstance(received, str)):
        return kind, None
    evidence = (*number_proof, *amount_proof, *identity.supplier.evidence, *identity.recipient.evidence,
                Evidence(f"inbox/ap/{document.doc_id}/message.json", "received_at", quote=received))
    return kind, DuplicateRecord(
        document.doc_id, identity.recipient.identity, identity.supplier.identity, currency, number,
        received, gross, tuple(dict.fromkeys(evidence)), status="RECEIVED",
        service_period=f"{start}/{end}" if start and end else None, document_type=kind)


def _vendor_prefixes(history: Iterable[DuplicateRecord]) -> dict[tuple[str, str], tuple[str, ...]]:
    """Leading letters a vendor's registered numbers carry: its evidenced numbering profile."""
    prefixes = {}
    for record in history:
        match = re.match(r"[A-Z]+", record.number.upper())
        if match:
            prefixes.setdefault((record.company, record.vendor), set()).add(match[0])
    return {key: tuple(sorted(value)) for key, value in prefixes.items()}


def month_duplicate_results(documents: Iterable[MonthDocument], data: PhaseData) -> dict[str, DuplicateResult]:
    """Duplicate/reissue result per invoice-like (or untyped) document of the month.

    ERP history plus every bound month observation is the inventory; it is only
    complete when every month document is bound or typed outside invoice scope.
    """
    catalog = IdentityCatalog.from_phase(data)
    history = registered_duplicate_records(data)
    prefixes = _vendor_prefixes(history)
    bound, unbound = [], []
    for document in documents:
        kind, record = month_record(document, catalog)
        if record is not None:
            bound.append(record)
        elif kind is None or kind in INVOICE_TYPES:
            unbound.append(document.doc_id)
    inventory = (*history, *bound)
    results = {doc_id: DuplicateResult("UNKNOWN", diagnostics=("DUPLICATE_FACTS_UNBOUND",)) for doc_id in unbound}
    for record in bound:
        try:
            results[record.doc_id] = duplicate_result(
                record, inventory, inventory_complete=not unbound,
                confirmed_prefixes=prefixes.get((record.company, record.vendor), ()))
        except ValueError as error:
            results[record.doc_id] = DuplicateResult("UNKNOWN", diagnostics=(f"DUPLICATE_INPUT_INVALID:{error}",))
    return results
