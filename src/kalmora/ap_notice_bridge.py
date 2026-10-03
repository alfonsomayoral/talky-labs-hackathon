"""Strict source-to-chronology integration for AP notices (#140).

The existing engines own actions and policy ordering. This boundary supplies
only agreed, evidence-bearing observations and keeps incomplete inventories
visible. It never writes ERP, reads Golden or infers receipt from issue dates.
"""
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
import re
from types import MappingProxyType

from .ap_chronology import KINDS, invoice_state, receipt_key, replay_events, validate_scope
from .ap_payment import ACTIONS, apply_notice
from .documents.normalization import _date as source_date
from .facts import DocumentFacts, Evidence, Fact
from .model.ap_event import ApEvent
from .model.ap_notice_resolution import NoticeResolution
from .model.ap_scope import ApScope
from .model.ap_timeline_state import ApTimelineState
from .model.invoice_event_state import InvoiceEventState


NOTICE_BRIDGE_VERSION = "ap-notice-bridge-v1"


def _aliases(*names: str) -> tuple[str, ...]:
    """Explicit canonical names and their literal raw counterparts, no fuzzy labels."""
    return (*names, *("raw." + name for name in names))


START = {
    "CONTRACTOR_TAX_CERTIFICATE": _aliases("certificate_valid_from", "valid_from",
        "certificate_issue_date", "certificate_issued_on", "issued_on"),
    "FACTORING_NOTICE": _aliases("factoring_effective_date", "valid_from"),
    "TAX_GARNISHMENT_ORDER": _aliases("embargo_date", "valid_from"),
    "BANK_DETAILS_CHANGE": _aliases("bank_details_effective_date", "valid_from"),
}
END = {
    "CONTRACTOR_TAX_CERTIFICATE": _aliases("certificate_valid_until", "certificate_expiry_date",
        "contractor_certificate_valid_until", "certificate_tax_valid_until", "valid_until"),
    "FACTORING_NOTICE": _aliases("factoring_valid_until", "factoring_expiry_date", "valid_until"),
    "TAX_GARNISHMENT_ORDER": _aliases("embargo_valid_until", "valid_until"),
    "BANK_DETAILS_CHANGE": _aliases("bank_details_valid_until", "valid_until"),
}
REFERENCE = _aliases("assigned_invoice_number", "referenced_invoice_number", "invoice_reference",
                     "invoice_number", "original_invoice_reference")
SIGNED = _aliases("signed", "signature_present", "bank_letter_signed")
BANK_CERTIFICATE = _aliases("bank_certificate_present", "bank_certificate_attached")
BANK_REGISTERED = _aliases("bank_change_registered", "registered_bank_change")
SCOPE_FIELDS = {
    "company": _aliases("company", "company_code"),
    "vendor": _aliases("vendor", "vendor_id"),
    "currency": _aliases("currency", "document_currency"),
}


def _validate_fields(fields: Mapping[str, Sequence[Fact]]) -> None:
    if (not isinstance(fields, Mapping) or any(not isinstance(name, str) or not name
            or not isinstance(values, Sequence) or isinstance(values, (str, bytes))
            or any(not isinstance(fact, Fact) for fact in values)
            for name, values in fields.items())):
        raise TypeError("notice fields require named sequences of Fact")


def _evidence(items: Iterable[Evidence]) -> tuple[Evidence, ...]:
    return tuple(sorted(set(items), key=lambda proof: (proof.document, proof.field,
        proof.page or 0, proof.quote is not None, proof.quote or "")))


def _proof(fields: Mapping[str, Sequence[Fact]]) -> tuple[Evidence, ...]:
    return _evidence(fact.evidence for name in sorted(fields) for fact in fields[name])


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("nonempty source text required")
    return value.strip()


def _boolean(value: object) -> bool:
    if type(value) is not bool:
        raise ValueError("observed boolean required")
    return value


def _bank(value: object) -> str:
    return re.sub(r"[\s.\-]", "", _text(value)).upper()


def _receipt(value: object) -> str:
    text = _text(value)
    receipt_key(text)
    return text


def _observed(fields, names, label, parse, *, required=False):
    """Resolve every candidate, retaining explicit absence and conflict evidence."""
    candidates = tuple(fact for name in names for fact in fields.get(name, ()))
    proof = _evidence(fact.evidence for fact in candidates)
    if not candidates:
        return None, proof, (f"MISSING:{label}",) if required else ()
    try:
        values = tuple(None if fact.value is None else parse(fact.value) for fact in candidates)
    except (TypeError, ValueError):
        return None, proof, (f"INVALID:{label}",)
    first = values[0]
    if any(type(value) is not type(first) or value != first for value in values[1:]):
        return None, proof, (f"CONFLICT:{label}",)
    return first, proof, (f"UNKNOWN:{label}",) if required and first is None else ()


def _bank_verification(fields):
    signed, signed_proof, signed_notes = _observed(fields, SIGNED, "signed", _boolean, required=True)
    certificate, certificate_proof, certificate_notes = _observed(
        fields, BANK_CERTIFICATE, "bank_certificate_present", _boolean, required=True)
    notes = (*signed_notes, *certificate_notes)
    if not notes and (signed is not True or certificate is not True):
        notes = ("BANK_CHANGE_NOT_VERIFIED",)
    return True if not notes else None, _evidence((*signed_proof, *certificate_proof)), notes


def _scope_notes(fields, scope):
    notes = []
    for label, aliases in SCOPE_FIELDS.items():
        if not any(name in fields for name in aliases):
            continue
        parse = (lambda value: _text(value).upper()) if label == "currency" else _text
        value, _, field_notes = _observed(fields, aliases, label, parse, required=True)
        notes.extend(field_notes)
        if not field_notes and value != getattr(scope, label):
            notes.append("NOTICE_SCOPE_CONFLICT:" + label)
    return tuple(notes)


def _bound_bank_event(event, fields, invoice_date):
    """Verification belongs to this exact account, scope and observed validity."""
    _, _, flags = _bank_verification(fields)
    value, _, value_notes = _observed(fields, _aliases("new_iban", "iban", "value"),
                                    "value", _bank, required=True)
    notes = [*flags, *value_notes, *_scope_notes(fields, event.scope)]
    if not value_notes:
        try:
            matched = value == _bank(event.value)
        except ValueError:
            matched = False
        if not matched:
            notes.append("BANK_EVENT_VALUE_CONFLICT")
    if event.verified is False:
        notes.append("BANK_EVENT_NOT_VERIFIED")
    for attr, aliases in (("valid_from", START["BANK_DETAILS_CHANGE"]),
                          ("valid_until", END["BANK_DETAILS_CHANGE"])):
        if not any(name in fields for name in aliases):
            continue
        observed, _, validity_notes = _observed(fields, aliases, attr, source_date)
        notes.extend(validity_notes)
        if not validity_notes and observed != getattr(event, attr):
            notes.append("BANK_EVENT_VALIDITY_CONFLICT:" + attr)
    if event.valid_until is not None:
        try:
            expired = source_date(event.valid_until) < source_date(invoice_date)
        except ValueError:
            notes.append("BANK_EVENT_VALIDITY_INVALID")
        else:
            if expired:
                # Do not let an engine that accepts registered bank changes use
                # evidence outside its explicit authorization interval.
                notes.append("BANK_EVENT_AUTHORIZATION_EXPIRED")
    if event.received_at is None:
        registered, _, registration_notes = _observed(fields, BANK_REGISTERED,
            "bank_change_registered", _boolean, required=True)
        notes.extend(registration_notes)
        if not registration_notes and registered is not True:
            notes.append("BANK_CHANGE_NOT_REGISTERED")
    return replace(event, verified=True if not notes else None,
        value=value if not notes else event.value,
        evidence=_evidence((*event.evidence, *_proof(fields)))), tuple(notes)


def _unknown(document_type, state, proof, notes) -> NoticeResolution:
    # Incomplete integration facts cannot authorize an operative action, even
    # when the policy engine assigns an action to the document's known type.
    return NoticeResolution("UNKNOWN", None, state, evidence=proof,
        diagnostics=tuple(dict.fromkeys(("NOTICE_FACTS_UNKNOWN", *notes))))


def resolve_ap_notice(
    document_type: str, *, fields: Mapping[str, Sequence[Fact]], company: str,
    vendor: str, currency: str, metadata: DocumentFacts,
    state: ApTimelineState = ApTimelineState(),
) -> NoticeResolution:
    """Bind one explicitly classified notice to its resolved scope and source facts.

    Missing/conflicting notice facts produce UNKNOWN with the original state.
    Informational documents use NONE and never create an event. The caller must
    not declare the notice inventory complete merely because every task was read.
    """
    if document_type not in ACTIONS:
        raise ValueError("document is not a supported non-invoice notice")
    _validate_fields(fields)
    if not isinstance(metadata, DocumentFacts) or not isinstance(state, ApTimelineState):
        raise TypeError("notice metadata/state require DocumentFacts/ApTimelineState")
    scope = ApScope(company, vendor, currency)
    validate_scope(scope)
    proof = _evidence((*_proof(fields), *_proof(metadata.fields)))
    if ACTIONS[document_type] == "NONE":
        return replace(apply_notice(document_type, state=state), evidence=proof)

    doc_id, _, id_notes = _observed(metadata.fields, ("doc_id",), "doc_id", _text, required=True)
    received, _, receipt_notes = _observed(metadata.fields, ("received_at",), "received_at", _receipt,
                                         required=True)
    start, _, start_notes = _observed(fields, START[document_type], "valid_from", source_date,
        required=document_type in {"FACTORING_NOTICE", "CONTRACTOR_TAX_CERTIFICATE"})
    end, _, end_notes = _observed(fields, END[document_type], "valid_until", source_date,
        required=document_type == "CONTRACTOR_TAX_CERTIFICATE")
    reference, _, reference_notes = _observed(fields, REFERENCE, "invoice_number", _text)
    value_names = (_aliases("factor_iban", "new_iban", "iban", "value") if document_type == "FACTORING_NOTICE"
                   else _aliases("new_iban", "iban", "value") if document_type == "BANK_DETAILS_CHANGE" else ())
    value, _, value_notes = _observed(fields, value_names, "value", _bank,
                                    required=document_type == "BANK_DETAILS_CHANGE")
    verified, verification_notes = None, ()
    if document_type == "BANK_DETAILS_CHANGE":
        verified, _, verification_notes = _bank_verification(fields)
        verification_notes = (*verification_notes, *_scope_notes(fields, scope))
    notes = (*id_notes, *receipt_notes, *start_notes, *end_notes, *reference_notes,
             *value_notes, *verification_notes)
    if notes:
        return _unknown(document_type, state, proof, notes)

    # ID binds the task and original attachment paths, not whichever candidate
    # happened to be selected first. Changed observations retain that identity
    # so replay catches a conflicting reinterpretation instead of adding an event.
    documents = sorted({fact.evidence.document for values in fields.values() for fact in values})
    identity = hashlib.sha256("\n".join(documents).encode()).hexdigest()[:16]
    event = ApEvent(f"{doc_id}:{document_type}:{identity}", scope, document_type, proof,
                    received_at=received, valid_from=start, valid_until=end,
                    verified=verified, value=value, invoice_number=reference)
    try:
        return apply_notice(document_type, event, state)
    except ValueError as error:
        return _unknown(document_type, state, proof, (f"NOTICE_EVENT_INVALID:{error}",))


@dataclass(frozen=True)
class StrictInvoiceEventSnapshot:
    state: InvoiceEventState
    events: tuple[ApEvent, ...]
    complete_kinds: tuple[str, ...]
    inventory_evidence: Mapping[str, tuple[Evidence, ...]]
    diagnostics: tuple[str, ...] = ()


def strict_invoice_events(
    events: Iterable[ApEvent] | ApTimelineState, scope: ApScope, invoice_date: str,
    received_at: str, month: str, *, invoice_number: str | None = None,
    bank_iban: str | None = None, complete_kinds: Iterable[str] = (),
    inventory_evidence: Mapping[str, tuple[Evidence, ...]] | None = None,
    uncertain_kinds: Iterable[str] = (), incomplete_sources: Iterable[str] = (),
    bank_fields: Mapping[tuple[ApScope, str], Mapping[str, Sequence[Fact]]] | None = None,
) -> StrictInvoiceEventSnapshot:
    """Query the real chronology engine with strict copies of the supplied events.

    An embargo without a documented receipt cannot use from_date as proof of
    prior reception. Bank events need both original signature and certificate
    observations, supplied by (scope, event_id); verified/domain alone is not
    sufficient. Explicit source failures remove all completeness claims.
    """
    validate_scope(scope)
    supplied = tuple(events.events if isinstance(events, ApTimelineState) else events)
    complete, uncertain = set(complete_kinds), set(uncertain_kinds)
    if not complete.issubset(KINDS) or not uncertain.issubset(KINDS):
        raise ValueError("unknown complete/uncertain event kind")
    failures = tuple(incomplete_sources)
    if any(not isinstance(value, str) or not value for value in failures):
        raise ValueError("incomplete sources require diagnostic identities")
    inventories = dict(inventory_evidence or {})
    if any(kind not in KINDS or not isinstance(proof, tuple) or not proof
           or any(not isinstance(item, Evidence) for item in proof)
           for kind, proof in inventories.items()):
        raise ValueError("inventory evidence requires known kinds and source Evidence")
    notes = [*("SOURCE_INCOMPLETE:" + value for value in failures)]
    if failures:
        uncertain.update(KINDS)
    sanitized = []
    for event in supplied:
        if not isinstance(event, ApEvent):
            raise TypeError("chronology requires ApEvent observations")
        if event.scope != scope:
            sanitized.append(event)
            continue
        if event.kind == "TAX_GARNISHMENT_ORDER" and event.received_at is None:
            event = replace(event, valid_from=None)
            uncertain.add(event.kind)
            notes.append("EMBARGO_RECEIPT_UNKNOWN:" + event.event_id)
        if event.kind == "BANK_DETAILS_CHANGE":
            fields = (bank_fields or {}).get((event.scope, event.event_id), {})
            _validate_fields(fields)
            event, verification_notes = _bound_bank_event(event, fields, invoice_date)
            if event.verified is not True:
                uncertain.add(event.kind)
                notes.extend(f"{event.event_id}:{note}" for note in verification_notes)
        sanitized.append(event)
    for kind in sorted(complete - inventories.keys()):
        notes.append("INVENTORY_EVIDENCE_MISSING:" + kind)
    effective = complete.intersection(inventories).difference(uncertain)
    timeline = replay_events(sanitized)
    state = invoice_state(timeline, scope, invoice_date, received_at, month,
                          invoice_number=invoice_number, bank_iban=bank_iban,
                          complete_kinds=effective)
    # A proved assignment exists even when unseen/failed competing notices could
    # change the operative recipient. A bank letter cannot settle a conflicting
    # or incomplete inventory of alternative bank instructions.
    if "FACTORING_NOTICE" in uncertain and state.factoring_active is True:
        state = replace(state, factoring=None, factoring_bank_supported=None)
        notes.append("FACTORING_NOTICE:OPERATIVE_INVENTORY_UNKNOWN")
    if "BANK_DETAILS_CHANGE" in uncertain and state.bank_change_supported is True:
        state = replace(state, bank_change=None, bank_change_supported=None)
        notes.append("BANK_DETAILS_CHANGE:OPERATIVE_INVENTORY_UNKNOWN")
    notes.extend("INVENTORY_UNKNOWN:" + kind for kind in sorted(uncertain))
    diagnostics = tuple(dict.fromkeys((*state.diagnostics, *notes)))
    state = replace(state, diagnostics=diagnostics)
    return StrictInvoiceEventSnapshot(state, timeline.events, tuple(sorted(effective)),
        MappingProxyType({kind: inventories[kind] for kind in sorted(effective)}), diagnostics)
