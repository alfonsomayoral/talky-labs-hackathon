"""Pure AP chronology from explicit facts (policy §2.1–2.2, issue #46).

No extraction, sender inference, posting or output serialization. Registered
masters are baselines; issued/valid dates must never invent a receipt timestamp.
"""
from datetime import date, datetime, timezone
from typing import Iterable, Mapping

from .data import PhaseData
from .facts import Evidence, Fact
from .model.ap_event import ApEvent
from .model.ap_scope import ApScope
from .model.ap_timeline_state import ApTimelineState
from .model.invoice_event_state import InvoiceEventState

KINDS = ("CONTRACTOR_TAX_CERTIFICATE", "FACTORING_NOTICE",
         "TAX_GARNISHMENT_ORDER", "BANK_DETAILS_CHANGE")


def _date(value: str) -> date:
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError("date must be YYYY-MM-DD")
    return parsed


def receipt_key(value: str) -> datetime:
    """Stable UTC ordering; package timestamps without a zone use wall-clock UTC.

    Date-only receipts are allowed for history but their same-day ordering is
    unknown. Callers must not mix local timestamps from different time zones.
    """
    if len(value) == 10:
        _date(value)
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def validate_scope(scope: ApScope) -> None:
    if not isinstance(scope, ApScope) or any(not isinstance(v, str) or not v
                                           for v in (scope.company, scope.vendor, scope.currency)):
        raise ValueError("explicit company, vendor and currency are required")


def _validate(event: ApEvent) -> None:
    validate_scope(event.scope)
    if not isinstance(event.event_id, str) or not event.event_id or event.kind not in KINDS:
        raise ValueError("event requires stable identity and supported kind")
    if not isinstance(event.evidence, tuple) or not event.evidence or any(not isinstance(e, Evidence) for e in event.evidence):
        raise ValueError("event requires source Evidence")
    if event.received_at is not None:
        receipt_key(event.received_at)
    start = _date(event.valid_from) if event.valid_from is not None else None
    end = _date(event.valid_until) if event.valid_until is not None else None
    if start is not None and end is not None and start > end:
        raise ValueError("validity interval is reversed")
    if event.verified is not None and type(event.verified) is not bool:
        raise ValueError("verified is boolean or unknown")
    for value in (event.value, event.invoice_number):
        if value is not None and (not isinstance(value, str) or not value):
            raise ValueError("event references must be nonempty strings")


def event_key(event: ApEvent):
    """Receipt, validity, stable event ID: never rely on filesystem/input order."""
    return (event.scope, event.received_at is not None,
            receipt_key(event.received_at) if event.received_at else datetime.min.replace(tzinfo=timezone.utc),
            event.valid_from or "", event.event_id)


def replay_events(events: Iterable[ApEvent], state: ApTimelineState = ApTimelineState()) -> ApTimelineState:
    """Return a new state; exact repeated events are idempotent, conflicts fail."""
    by_id = {}
    for event in (*state.events, *tuple(events)):
        _validate(event)
        key = (event.scope, event.event_id)
        if key in by_id and by_id[key] != event:
            raise ValueError("conflicting event identity")
        by_id[key] = event
    return ApTimelineState(tuple(sorted(by_id.values(), key=event_key)))


def _before(received: str, invoice_received: str) -> bool | None:
    a, b = receipt_key(received), receipt_key(invoice_received)
    if a.date() == b.date() and (len(received) == 10 or len(invoice_received) == 10):
        return None
    return a < b


def _valid(event: ApEvent, invoice_date: date) -> bool | None:
    if event.valid_from is None:
        return None
    if _date(event.valid_from) > invoice_date:
        return False
    # Certificates require a documented expiry; assignments may be open ended.
    if event.kind == "CONTRACTOR_TAX_CERTIFICATE" and event.valid_until is None:
        return None
    return event.valid_until is None or invoice_date <= _date(event.valid_until)


def invoice_state(
    events: Iterable[ApEvent] | ApTimelineState, scope: ApScope,
    invoice_date: str, received_at: str, month: str, *,
    invoice_number: str | None = None, bank_iban: str | None = None,
    complete_kinds: Iterable[str] = (),
) -> InvoiceEventState:
    """Observe a reproducible invoice snapshot without mutating supplied state.

    Absence is unknown unless the caller declares the kind's inventory complete.
    Certificates/assignments use inclusive invoice-date validity and evidence
    known by invoice reception. Embargo must arrive strictly before the invoice.
    Verified bank changes registered or received anywhere in the closing month
    support the stated IBAN (§2.2); future months do not.
    """
    validate_scope(scope)
    inv_date, inv_received = _date(invoice_date), receipt_key(received_at)
    month_start = _date(month + "-01")
    if inv_received.strftime("%Y-%m") != month:
        raise ValueError("invoice reception must belong to closing month")
    complete = frozenset(complete_kinds)
    if not complete.issubset(KINDS):
        raise ValueError("unknown complete event kind")
    state = replay_events(events.events if isinstance(events, ApTimelineState) else events)
    diagnostics, observations, selected = [], {}, {}
    for kind in KINDS:
        matches, unknown = [], False
        for event in state.events:
            if event.scope != scope or event.kind != kind:
                continue
            if event.invoice_number is not None:
                if invoice_number is None:
                    unknown = True
                    diagnostics.append(f"{event.event_id}:INVOICE_REFERENCE_UNKNOWN")
                    continue
                if event.invoice_number != invoice_number:
                    continue
            if kind == "BANK_DETAILS_CHANGE":
                if event.received_at is not None and receipt_key(event.received_at).date() < month_start:
                    # A prior received change remains registered in the replay.
                    pass
                elif event.received_at is not None and receipt_key(event.received_at).strftime("%Y-%m") != month:
                    continue
                if event.verified is False:
                    continue
                if event.verified is None or event.value is None or bank_iban is None:
                    unknown = True
                    diagnostics.append(f"{event.event_id}:BANK_VERIFICATION_UNKNOWN")
                    continue
                if event.value == bank_iban:
                    matches.append(event)
                continue
            if kind == "TAX_GARNISHMENT_ORDER":
                if event.received_at is None:
                    unknown = True
                    diagnostics.append(f"{event.event_id}:EMBARGO_RECEIPT_UNKNOWN")
                    continue
                before = _before(event.received_at, received_at)
                if before is None:
                    unknown = True
                    diagnostics.append(f"{event.event_id}:RECEIPT_ORDER_UNKNOWN")
                elif before:
                    matches.append(event)
                continue
            if event.received_at is not None:
                if receipt_key(event.received_at) > inv_received:
                    continue
                if _before(event.received_at, received_at) is None:
                    unknown = True
                    diagnostics.append(f"{event.event_id}:RECEIPT_ORDER_UNKNOWN")
                    continue
            valid = _valid(event, inv_date)
            if valid is None:
                unknown = True
                diagnostics.append(f"{event.event_id}:VALIDITY_UNKNOWN")
            elif valid:
                matches.append(event)
        # Latest validity then receipt then ID settles equivalent observations.
        matches.sort(key=lambda e: (e.valid_from or "", event_key(e)))
        selected[kind] = matches[-1] if matches else None
        observations[kind] = True if matches else None if unknown or kind not in complete else False
        if observations[kind] is None and not unknown:
            diagnostics.append(f"{kind}:INVENTORY_UNKNOWN")
    factor = selected[KINDS[1]]
    factor_bank = observations[KINDS[1]]
    if factor is not None:
        factor_bank = None if factor.value is None or bank_iban is None else factor.value == bank_iban
    return InvoiceEventState(*(observations[k] for k in KINDS),
                             *(selected[k] for k in KINDS), tuple(sorted(set(diagnostics))), factor_bank)


def registered_events(data: PhaseData, scope: ApScope) -> ApTimelineState:
    """Read known vendor baseline and certificates through M0 PhaseData.

    AR factoring_assignments belongs to customers and is deliberately excluded.
    Vendor garnishment from_date is not documented as receipt: preserve unknown.
    Bank-history valid_to does not prove a signed bank-change letter.
    """
    validate_scope(scope)
    vendor = data.get("vendors", scope.vendor)
    if scope.company not in vendor["companies"] or scope.currency != vendor["currency"]:
        raise ValueError("vendor baseline does not match resolved AP scope")
    events = []
    for row in data.find("contractor_certificates", vendor=scope.vendor):
        events.append(ApEvent(row["reference"], scope, KINDS[0],
                              (Evidence("erp/contractor_certificates", row["reference"]),),
                              valid_from=row["issued_on"], valid_until=row["valid_until"]))
    payee = vendor.get("alternative_payee")
    if payee is not None:
        if payee.get("type") != "FACTOR":
            raise ValueError("unsupported registered alternative payee")
        events.append(ApEvent(f"{scope.vendor}:factor", scope, KINDS[1],
                              (Evidence("erp/vendors", f"{scope.vendor}.alternative_payee"),),
                              valid_from=payee.get("from_date"), value=payee.get("iban")))
    for row in vendor.get("garnishments", ()):
        events.append(ApEvent(row["ref"], scope, KINDS[2],
                              (Evidence("erp/vendors", f"{scope.vendor}.garnishments.{row['ref']}"),),
                              received_at=row.get("received_at") or row.get("received_on"),
                              valid_from=row.get("from_date")))
    return replay_events(events)


def event_support_facts(
    state: InvoiceEventState,
    inventory_evidence: Mapping[str, tuple[Evidence, ...]] | None = None,
) -> dict[str, tuple[Fact, ...]]:
    """Bridge to rule checks without inventing evidence for an absent event.

    A false observation requires the caller's evidence for its complete inventory.
    Unknown observations have no Fact candidates. Evidence describes derived
    policy support rather than pretending to have extracted it from an invoice.
    """
    result = {}
    for field, value, event, kind in (
        ("certificate_valid", state.certificate_valid, state.certificate, KINDS[0]),
        ("factoring_supported", state.factoring_bank_supported, state.factoring, KINDS[1]),
        ("embargo_active", state.embargo_active, state.embargo, KINDS[2]),
        ("signed_change_supported", state.bank_change_supported, state.bank_change, KINDS[3]),
    ):
        if value is None:
            result[field] = ()
            continue
        evidence = event.evidence if event is not None else (inventory_evidence or {}).get(kind, ())
        if not evidence:
            raise ValueError("false event support requires complete-inventory Evidence")
        result[field] = tuple(Fact(value, item) for item in evidence)
    return result
