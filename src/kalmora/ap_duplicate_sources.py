"""Bind the month's replayed AP sources and ERP history to the duplicate engine (#47).

No extraction, golden data, name similarity or vendor-currency defaults. A field
is bound only when every candidate of the invoice-typed attachments agrees.
"""
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace

from .ap_chronology import receipt_key
from .ap_duplicates import duplicate_result, registered_duplicate_records
from .ap_identity_sources import resolve_ap_identity
from .data import PhaseData
from .documents.ap_sources import APTaskSources
from .facts import DocumentFacts, Evidence
from .model.ap_duplicate_record import DuplicateRecord
from .model.ap_duplicate_result import DuplicateResult

INVOICE_TYPES = frozenset(("INVOICE", "CREDIT_NOTE", "DOWN_PAYMENT_REQUEST"))


def _agreed(sources: Sequence[DocumentFacts], name: str):
    facts = [fact for source in sources for fact in source.fields.get(name, ())]
    values = {fact.value for fact in facts}
    if len(values) != 1 or None in values:
        return None, ()
    return values.pop(), tuple(fact.evidence for fact in facts)


def month_record(task: APTaskSources, data: PhaseData) -> tuple[str | None, str | None, DuplicateRecord | None]:
    """Agreed document type, resolved vendor and the observation (None if not bindable).

    A failed or untyped attachment leaves the type unknown only when no other
    attachment of the task is typed; it never contributes facts.
    """
    typed = [(a.normalized.facts, a.classification.document_type) for a in task.attachments
             if a.error is None and a.classification is not None and a.classification.document_type]
    readable = [a.normalized.facts for a in task.attachments if a.error is None and a.normalized is not None]
    types = {kind for _, kind in typed}
    kind = types.pop() if len(types) == 1 else None
    sources = [facts for facts, attachment_type in typed if attachment_type == kind] or readable
    identity = resolve_ap_identity(sources, task.message.raw, data)
    if kind not in INVOICE_TYPES:
        return kind, identity.vendor_id, None
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
    received = task.message.received_at
    if identity.vendor_id is None or identity.company is None or not isinstance(number, str) or not received:
        return kind, identity.vendor_id, None
    evidence = (*number_proof, *amount_proof, *identity.evidence,
                Evidence(task.message.path, "received_at", quote=received))
    return kind, identity.vendor_id, DuplicateRecord(
        task.doc_id, identity.company, identity.vendor_id, currency, number, received, gross,
        tuple(dict.fromkeys(evidence)), status="RECEIVED",
        service_period=f"{start}/{end}" if start and end else None, document_type=kind)


def month_duplicate_results(tasks: Iterable[APTaskSources], data: PhaseData,
                            statuses: Mapping[str, str] | None = None) -> dict[str, DuplicateResult]:
    """Duplicate/reissue result per invoice-like or untyped task of the month.

    ERP history plus every bound month observation is the inventory. ``statuses``
    carries upstream month decisions (e.g. REJECT from #48); otherwise RECEIVED.
    A task that cannot be bound (failed extraction, unknown type or facts) blocks
    a negative answer only for documents it could precede: same or unknown vendor,
    received no later.
    """
    history = registered_duplicate_records(data)
    bound, unbound = [], {}
    for task in tasks:
        kind, vendor, record = month_record(task, data)
        if record is not None:
            bound.append(replace(record, status=(statuses or {}).get(task.doc_id, "RECEIVED")))
        elif kind is None or kind in INVOICE_TYPES:
            unbound[task.doc_id] = (vendor, task.message.received_at)
    inventory = (*history, *bound)
    results = {doc_id: DuplicateResult("UNKNOWN", diagnostics=("DUPLICATE_FACTS_UNBOUND",)) for doc_id in unbound}
    for record in bound:
        complete = not any(
            vendor in (None, record.vendor) and (not received or receipt_key(received) <= receipt_key(record.received_at))
            for vendor, received in unbound.values())
        try:
            results[record.doc_id] = duplicate_result(record, inventory, inventory_complete=complete)
        except ValueError as error:
            results[record.doc_id] = DuplicateResult("UNKNOWN", diagnostics=(f"DUPLICATE_INPUT_INVALID:{error}",))
    return results
