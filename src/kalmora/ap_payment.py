"""AP payment block/payee and simulated notice actions (policy §2.1–2.2).

UNKNOWN and diagnostics are internal states; never fabricate a contract decision
from incomplete extraction, rules or chronological evidence. No entries emitted.
"""
from typing import Mapping

from .ap_chronology import KINDS, replay_events
from .facts import Evidence
from .model.ap_event import ApEvent
from .model.ap_notice_resolution import NoticeResolution
from .model.ap_payment_resolution import PaymentResolution
from .model.ap_timeline_state import ApTimelineState
from .model.invoice_event_state import InvoiceEventState

ACTIONS = {
    "PROFORMA": "NONE",
    "VENDOR_STATEMENT": "NONE",
    "FACTORING_NOTICE": "REGISTER_ALTERNATIVE_PAYEE",
    "TAX_GARNISHMENT_ORDER": "REGISTER_EMBARGO",
    "BANK_DETAILS_CHANGE": "UPDATE_BANK_DETAILS",
    "CONTRACTOR_TAX_CERTIFICATE": "UPDATE_CONTRACTOR_CERTIFICATE",
}


def resolve_payment(
    duplicate_status: str, rejection_status: str, hold_status: str,
    construction_subcontractor: bool | None, events: InvoiceEventState,
    *, inventory_evidence: Mapping[str, tuple[Evidence, ...]] | None = None,
) -> PaymentResolution:
    """Final payment metadata only after all preceding rule stages clear.

    Accept stage statuses, so callers can pass RuleStage.status and
    DuplicateResult.status without coupling engines or changing shared contracts.
    The caller retains preceding-stage reasons; this module never invents them.
    """
    if duplicate_status not in ("CLEAR", "REISSUE", "DUPLICATE", "UNKNOWN"):
        raise ValueError("invalid duplicate stage")
    if rejection_status not in ("CLEAR", "REJECT", "UNKNOWN") or hold_status not in ("CLEAR", "HOLD", "UNKNOWN"):
        raise ValueError("invalid invoice rule stage")
    if construction_subcontractor is not None and type(construction_subcontractor) is not bool:
        raise ValueError("construction_subcontractor must be boolean or unknown")
    for stage, status in (("DUPLICATE", duplicate_status), ("REJECTION", rejection_status), ("HOLD", hold_status)):
        if status == "UNKNOWN":
            return PaymentResolution("UNKNOWN", diagnostics=(f"{stage}_STAGE_UNKNOWN",))
        if status in ("DUPLICATE", "REJECT", "HOLD"):
            return PaymentResolution(status)
    for value in (events.certificate_valid, events.factoring_active, events.embargo_active):
        if value is not None and type(value) is not bool:
            raise ValueError("chronology observations must be boolean or unknown")
    diagnostics, evidence = [], []
    inventories = inventory_evidence or {}
    if any(kind not in KINDS or not isinstance(proof, tuple) or not proof
           or any(not isinstance(item, Evidence) for item in proof)
           for kind, proof in inventories.items()):
        raise ValueError("complete inventories require structured source Evidence")
    def negative_evidence(kind):
        proof = inventories.get(kind)
        if not proof:
            diagnostics.append(f"{kind}:COMPLETE_INVENTORY_EVIDENCE_MISSING")
        else:
            evidence.extend(proof)
    block = None
    if construction_subcontractor is True:
        if events.certificate_valid is None:
            diagnostics.append("CONTRACTOR_CERTIFICATE_UNKNOWN")
        elif events.certificate_valid is False:
            negative_evidence("CONTRACTOR_TAX_CERTIFICATE")
            block = "CONTRACTOR_CERTIFICATE_EXPIRED"
    elif construction_subcontractor is None and events.certificate_valid is not True:
        diagnostics.append("CONSTRUCTION_SUBCONTRACTOR_UNKNOWN")
    if construction_subcontractor is not False and events.certificate is not None:
        evidence.extend(events.certificate.evidence)
    elif construction_subcontractor is not False and events.certificate_valid is True:
        diagnostics.append("CONTRACTOR_CERTIFICATE_EVIDENCE_UNKNOWN")
    factor, embargo = events.factoring_active, events.embargo_active
    payee = None
    if factor is True and embargo is True:
        # Policy specifies both independent outcomes, but no simultaneous ranking.
        diagnostics.append("PAYEE_CONFLICT")
    elif factor is None or embargo is None:
        diagnostics.append("PAYEE_STATE_UNKNOWN")
    elif factor:
        if events.factoring is None:
            diagnostics.append("FACTORING_RECIPIENT_UNKNOWN")
            diagnostics.extend(d for d in events.diagnostics if d.startswith("FACTORING_NOTICE:CONFLICT"))
        else:
            payee = "FACTOR"
    elif embargo:
        if events.embargo is None:
            diagnostics.append("EMBARGO_EVIDENCE_UNKNOWN")
        else:
            payee = "AEAT_EMBARGO"
    if factor is False:
        negative_evidence("FACTORING_NOTICE")
    if embargo is False:
        negative_evidence("TAX_GARNISHMENT_ORDER")
    if events.factoring is not None and factor:
        evidence.extend(events.factoring.evidence)
    if events.embargo is not None and embargo:
        evidence.extend(events.embargo.evidence)
    evidence = tuple(dict.fromkeys(evidence))
    if diagnostics:
        return PaymentResolution("UNKNOWN", evidence=evidence, diagnostics=tuple(diagnostics))
    return PaymentResolution("POST_PAYMENT_BLOCK" if block else "POST", block, payee, evidence)


def apply_notice(
    document_type: str, event: ApEvent | None = None,
    state: ApTimelineState = ApTimelineState(),
) -> NoticeResolution:
    """Register a complete explicit notice in simulated state, never in ERP.

    Unsupported/invoice document types are caller errors. Missing notice facts
    stay UNKNOWN. Bank changes require verified evidence, not merely a new IBAN.
    """
    if document_type not in ACTIONS:
        raise ValueError("document is not a supported non-invoice notice")
    action = ACTIONS[document_type]
    if action == "NONE":
        if event is not None:
            raise ValueError("informational document cannot change vendor state")
        return NoticeResolution("NOT_INVOICE", action, state)
    if event is None:
        return NoticeResolution("UNKNOWN", None, state, diagnostics=("NOTICE_FACTS_UNKNOWN",))
    if event.kind != document_type:
        raise ValueError("notice type and event kind disagree")
    # Validate even when incomplete, without applying it to the supplied state.
    replay_events((event,))
    missing = []
    if event.received_at is None:
        missing.append("NOTICE_RECEIPT_UNKNOWN")
    if document_type in ("FACTORING_NOTICE", "CONTRACTOR_TAX_CERTIFICATE") and event.valid_from is None:
        missing.append("NOTICE_VALIDITY_UNKNOWN")
    if document_type == "CONTRACTOR_TAX_CERTIFICATE" and event.valid_until is None:
        missing.append("CERTIFICATE_EXPIRY_UNKNOWN")
    if document_type == "BANK_DETAILS_CHANGE" and (event.verified is not True or event.value is None):
        missing.append("BANK_CHANGE_NOT_VERIFIED")
    if missing:
        return NoticeResolution("UNKNOWN", None, state, event.evidence, tuple(missing))
    updated = replay_events((event,), state)
    return NoticeResolution("NOT_INVOICE", action, updated, event.evidence)
