"""Bind classified notices and invoice facts to the payment engine (#50).

Scope (company, vendor, currency) comes from the identity binding (#42). No
extraction, identity inference, posting or ERP writes; contradictory or absent
facts stay unknown and the engines decide.
"""
from collections.abc import Iterable

from .ap_chronology import KINDS, invoice_state, registered_events, replay_events
from .ap_payment import apply_notice, resolve_payment
from .data import PhaseData
from .facts import DocumentFacts, Evidence
from .model.ap_event import ApEvent
from .model.ap_notice_resolution import NoticeResolution
from .model.ap_payment_resolution import PaymentResolution
from .model.ap_scope import ApScope
from .model.ap_timeline_state import ApTimelineState

# Event attribute -> normalized fact names, per notice kind.
NOTICE_FIELDS = {
    "CONTRACTOR_TAX_CERTIFICATE": {
        "valid_from": ("certificate_valid_from",),
        "valid_until": ("certificate_valid_until", "certificate_expiry_date",
                        "contractor_certificate_valid_until", "certificate_tax_valid_until")},
    "FACTORING_NOTICE": {"valid_from": ("factoring_effective_date",), "value": ("iban", "new_iban")},
    "TAX_GARNISHMENT_ORDER": {"value": ("embargo_reference",)},
    "BANK_DETAILS_CHANGE": {"valid_from": ("bank_details_effective_date",), "value": ("new_iban", "iban")},
}


def _single(facts: DocumentFacts, names: tuple[str, ...]):
    """One agreed value across the names, or None when absent or contradictory."""
    candidates = [fact for name in names for fact in facts.fields.get(name, ()) if fact.value is not None]
    if len({fact.value for fact in candidates}) != 1:
        return None, ()
    return candidates[0].value, tuple(fact.evidence for fact in candidates)


def notice_event(document_type: str, facts: DocumentFacts, *, doc_id: str,
                 received_at: str, scope: ApScope) -> ApEvent:
    """Observed notice as a chronology event; bank verification is never inferred."""
    evidence = [Evidence(f"inbox/ap/{doc_id}/message.json", "received_at", quote=received_at)]
    values = {}
    for attribute, names in NOTICE_FIELDS[document_type].items():
        values[attribute], proof = _single(facts, names)
        evidence.extend(proof)
    return ApEvent(doc_id, scope, document_type, tuple(dict.fromkeys(evidence)),
                   received_at=received_at, **values)


def resolve_notice(document_type: str, facts: DocumentFacts, *, doc_id: str, received_at: str,
                   scope: ApScope | None, state: ApTimelineState = ApTimelineState()) -> NoticeResolution:
    """NOT_INVOICE action and the simulated state after registering the notice."""
    if document_type not in NOTICE_FIELDS:
        return apply_notice(document_type, state=state)
    if scope is None:
        return NoticeResolution("UNKNOWN", None, state, diagnostics=("NOTICE_SCOPE_UNKNOWN",))
    event = notice_event(document_type, facts, doc_id=doc_id, received_at=received_at, scope=scope)
    return apply_notice(document_type, event, state)


def resolve_invoice_payment(*, data: PhaseData, scope: ApScope, invoice_date: str, received_at: str,
                            notices: ApTimelineState | Iterable[ApEvent], notices_complete: bool,
                            duplicate_status: str, rejection_status: str,
                            hold_status: str) -> PaymentResolution:
    """Payment block/payee from ERP baselines plus the month's registered notices.

    `notices_complete` asserts every inbox document of the month was classified,
    so an absent notice is a proved absence; otherwise absence stays unknown.
    Construction subcontractors are the vendors whose master default is ISP de obra.
    """
    events = notices.events if isinstance(notices, ApTimelineState) else tuple(notices)
    state = replay_events(events, registered_events(data, scope))
    observed = invoice_state(state, scope, invoice_date, received_at, received_at[:7],
                             complete_kinds=KINDS if notices_complete else ())
    inventories = {}
    if notices_complete:
        tables = ("erp/contractor_certificates.jsonl", "erp/vendors.jsonl", "erp/vendors.jsonl", "erp/vendors.jsonl")
        inventories = {kind: (Evidence(table, f"vendor={scope.vendor}"),
                              Evidence("inbox/ap", f"classified {kind} received in {received_at[:7]}"))
                       for kind, table in zip(KINDS, tables)}
    tax_code = data.get("vendors", scope.vendor).get("default_tax_code")
    return resolve_payment(duplicate_status, rejection_status, hold_status,
                           None if tax_code is None else tax_code == "SISP", observed,
                           inventory_evidence=inventories)
