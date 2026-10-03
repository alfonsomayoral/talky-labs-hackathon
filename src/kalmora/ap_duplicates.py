"""Evidence-led invoice duplicate and corrected reissue detection (#47)."""
from typing import Iterable

from .ap_chronology import receipt_key
from .data import PhaseData
from .facts import Evidence
from .model.ap_duplicate_record import DuplicateRecord
from .model.ap_duplicate_result import DuplicateResult

STATUSES = frozenset(("RECEIVED", "POST", "POST_PAYMENT_BLOCK", "HOLD", "REJECT", "DUPLICATE"))


def normalize_number(number: str, confirmed_prefixes: Iterable[str] = ()) -> str:
    """Strip separators and *explicitly confirmed* prefixes, preserve all digits.

    Prefixes belong to a caller's evidenced vendor-specific normalization profile.
    No F/FV/TKD prefix, numeric suffix, leading zero or period is inferred.
    """
    if not isinstance(number, str) or not number.strip():
        raise ValueError("invoice number is required")
    if isinstance(confirmed_prefixes, (str, bytes)):
        raise ValueError("confirmed prefixes require an explicit sequence")
    def compact(value):
        return "".join(c for c in value.upper() if c not in "-/" and not c.isspace())
    normalized = compact(number)
    if not normalized:
        raise ValueError("normalized invoice number cannot be empty")
    candidates = set()
    for prefix in confirmed_prefixes:
        if not isinstance(prefix, str) or not compact(prefix):
            raise ValueError("confirmed prefix cannot be empty")
        prefix = compact(prefix)
        if normalized.startswith(prefix):
            candidates.add(normalized[len(prefix):])
    if len(candidates) > 1 or "" in candidates:
        raise ValueError("ambiguous or empty normalized invoice number")
    return next(iter(candidates)) if candidates else normalized


def _validate(record: DuplicateRecord) -> None:
    for value in (record.doc_id, record.company, record.vendor, record.number, record.document_type):
        if not isinstance(value, str) or not value:
            raise ValueError("invoice observation requires identity and number")
    for value in (record.currency, record.status, record.corrected_by, record.duplicate_of, record.service_period):
        if value is not None and (not isinstance(value, str) or not value):
            raise ValueError("optional invoice references must be nonempty strings")
    receipt_key(record.received_at)
    if record.amount_cents is not None and type(record.amount_cents) is not int:
        raise ValueError("invoice amount requires integer cents")
    if not isinstance(record.evidence, tuple) or not record.evidence or any(not isinstance(e, Evidence) for e in record.evidence):
        raise ValueError("invoice observation requires source Evidence")


def _key(record):
    return (receipt_key(record.received_at), record.doc_id)


def _earlier(prior, current):
    a, b = receipt_key(prior.received_at), receipt_key(current.received_at)
    if a.date() == b.date() and (len(prior.received_at) == 10 or len(current.received_at) == 10):
        return None
    # Exact same reception timestamps are settled by stable document ID.
    return (a, prior.doc_id) < (b, current.doc_id)


def duplicate_result(
    current: DuplicateRecord, history: Iterable[DuplicateRecord], *,
    inventory_complete: bool = False, confirmed_prefixes: Iterable[str] = (),
) -> DuplicateResult:
    """Find the first evidenced duplicate, or an explicit corrected reissue.

    Callers pass both ERP history and earlier monthly observations. A complete
    inventory is required for a negative result. Logs missing currency/amount,
    unknown status or same-day date-only order can prevent a safe conclusion.
    A REJECT linked by corrected_by to this exact document is a reissue, even if
    its number/gross is unchanged. An unlinked REJECT is not guessed corrected.
    """
    _validate(current)
    if current.currency is None or current.amount_cents is None:
        return DuplicateResult("UNKNOWN", diagnostics=("CURRENT_IDENTITY_OR_AMOUNT_UNKNOWN",))
    if type(inventory_complete) is not bool:
        raise ValueError("inventory_complete must be boolean")
    prefixes = tuple(confirmed_prefixes)
    number = normalize_number(current.number, prefixes)
    by_id = {}
    for record in history:
        _validate(record)
        identity = (record.company, record.doc_id)
        if identity in by_id and by_id[identity] != record:
            raise ValueError("conflicting historical document identity")
        by_id[identity] = record
    records = sorted(by_id.values(), key=_key)
    candidates, unknowns, corrections = [], [], []
    for prior in records:
        if prior.doc_id == current.doc_id and prior.company == current.company:
            continue
        if (prior.company, prior.vendor, prior.document_type) != (current.company, current.vendor, current.document_type):
            continue
        if prior.currency is not None and prior.currency != current.currency:
            continue
        correction = prior.corrected_by == current.doc_id and prior.status == "REJECT"
        if not correction:
            if normalize_number(prior.number, prefixes) != number:
                continue
            if prior.status == "REJECT" and prior.corrected_by is not None:
                continue
            if prior.service_period is not None and current.service_period is not None and prior.service_period != current.service_period:
                continue
            if prior.amount_cents is not None and prior.amount_cents != current.amount_cents:
                continue
        earlier = _earlier(prior, current)
        if earlier is False:
            continue
        def unknown(code):
            unknowns.append((prior, f"{prior.doc_id}:{code}"))
        if earlier is None:
            unknown("RECEPTION_ORDER_UNKNOWN")
            continue
        if correction:
            corrections.append(prior)
            continue
        if prior.currency is None or prior.amount_cents is None:
            unknown("CURRENCY_OR_AMOUNT_UNKNOWN")
            continue
        if prior.amount_cents != current.amount_cents:
            continue
        if (prior.service_period is None) != (current.service_period is None):
            unknown("SERVICE_PERIOD_UNKNOWN")
            continue
        if prior.status not in STATUSES:
            unknown("STATUS_UNKNOWN")
            continue
        if prior.status == "REJECT":
            unknown("REJECTED_REISSUE_RELATION_UNKNOWN")
            continue
        if prior.status == "DUPLICATE":
            root = by_id.get((prior.company, prior.duplicate_of))
            if (root is None or root.status not in ("RECEIVED", "POST", "POST_PAYMENT_BLOCK", "HOLD")
                    or (root.company, root.vendor, root.currency, root.document_type) !=
                    (current.company, current.vendor, current.currency, current.document_type)
                    or normalize_number(root.number, prefixes) != number
                    or root.amount_cents != current.amount_cents
                    or _earlier(root, current) is not True):
                unknown("DUPLICATE_ROOT_UNKNOWN")
                continue
            candidates.append(root)
        else:
            candidates.append(prior)
    if candidates:
        first = min(candidates, key=_key)
        blocking = [diagnostic for prior, diagnostic in unknowns if _key(prior) <= _key(first)]
        if not blocking:
            return DuplicateResult("DUPLICATE", duplicate_of=first.doc_id,
                                   evidence=(*current.evidence, *first.evidence))
        return DuplicateResult("UNKNOWN", diagnostics=tuple(sorted(set(blocking))))
    diagnostics = [diagnostic for _, diagnostic in unknowns]
    if not inventory_complete:
        diagnostics.append("DUPLICATE_INVENTORY_UNKNOWN")
    if diagnostics:
        return DuplicateResult("UNKNOWN", diagnostics=tuple(sorted(set(diagnostics))))
    if corrections:
        first = min(corrections, key=_key)
        return DuplicateResult("REISSUE", reissue_of=first.doc_id,
                               evidence=(*current.evidence, *first.evidence))
    return DuplicateResult("CLEAR", evidence=current.evidence)


def registered_duplicate_records(data: PhaseData) -> tuple[DuplicateRecord, ...]:
    """Join ERP invoices and processing log by company/doc_id without guesses.

    Log decisions preserve original HOLD/REJECT status and corrected_by. Posted
    invoice rows supply amounts/currency; log-only rows retain missing values.
    Neither default vendor currency nor a correction's gross fills absent facts.
    """
    invoices = {}
    for row in data.table("ap_invoices"):
        key = (row["company"], row["doc_id"])
        if key in invoices:
            raise ValueError("duplicate ERP invoice identity")
        invoices[key] = row
    logs = {}
    for row in data.table("ap_document_log"):
        key = (row["company"], row["doc_id"])
        if key in logs:
            raise ValueError("duplicate AP log identity")
        logs[key] = row
    records = []
    for key in sorted(invoices.keys() | logs.keys()):
        invoice, log = invoices.get(key), logs.get(key)
        if invoice and log and any(invoice[field] != log[field] for field in ("vendor", "number", "kind")):
            raise ValueError("conflicting invoice and log identity")
        source = invoice or log
        kind = source["kind"].upper()
        if kind not in ("INVOICE", "CREDIT_NOTE", "DOWN_PAYMENT_REQUEST"):
            continue
        evidence = tuple(Evidence(f"erp/{name}", key[1]) for name, row in
                         (("ap_invoices", invoice), ("ap_document_log", log)) if row is not None)
        records.append(DuplicateRecord(
            key[1], key[0], source["vendor"], invoice.get("currency") if invoice else None,
            source["number"], invoice.get("received_on") if invoice else log["received_on"],
            invoice.get("gross") if invoice else None, evidence,
            status=(log or invoice).get("decision"), corrected_by=log.get("corrected_by") if log else None,
            duplicate_of=log.get("duplicate_of") if log else None,
            service_period=invoice.get("service_period") if invoice else None, document_type=kind,
        ))
    return tuple(sorted(records, key=lambda r: (r.company, *_key(r))))
