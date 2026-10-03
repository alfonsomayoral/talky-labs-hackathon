"""Bind inbox notices and ERP history to the AP chronology (policy §2.1–2.2, #46).

Reception is the message `received_at`; vigency comes only from extracted facts.
No golden data, name similarity or decision output.
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .ap_chronology import KINDS, invoice_state, receipt_key, registered_events
from .ap_identity_sources import _domain, resolve_ap_identity
from .data import PhaseData
from .documents.normalization import _date as source_date
from .facts import DocumentFacts, Evidence
from .model.ap_event import ApEvent
from .model.ap_scope import ApScope
from .model.invoice_event_state import InvoiceEventState

# kind -> (valid_from, valid_until, value) fields; all candidates must agree.
FIELDS = {
    "CONTRACTOR_TAX_CERTIFICATE": (("certificate_valid_from",),
                                   ("certificate_valid_until", "certificate_expiry_date",
                                    "contractor_certificate_valid_until", "certificate_tax_valid_until"), ()),
    "FACTORING_NOTICE": (("factoring_effective_date",), (), ("new_iban", "iban")),
    "TAX_GARNISHMENT_ORDER": (("embargo_date",), (), ()),
    "BANK_DETAILS_CHANGE": (("bank_details_effective_date",), (), ("new_iban", "iban")),
}


@dataclass(frozen=True)
class NoticeBinding:
    events: tuple[ApEvent, ...]
    diagnostics: tuple[str, ...] = ()


def _one(facts: DocumentFacts, names, label, diagnostics, parse=None):
    """The agreed value of the named fields with all its evidence, else unknown."""
    found = [fact for name in names for fact in facts.fields.get(name, ()) if fact.value is not None]
    try:
        values = {parse(fact.value) if parse else fact.value for fact in found}
    except ValueError:
        diagnostics.append(f"{label}:INVALID")
        return None, ()
    if len(values) > 1:
        diagnostics.append(f"{label}:CONFLICT")
    if len(values) != 1:
        return None, ()
    return values.pop(), tuple(fact.evidence for fact in found)


def notice_events(message: Mapping[str, Any],
                  documents: Iterable[tuple[DocumentFacts, str | None]],
                  data: PhaseData) -> NoticeBinding:
    """ApEvents for each classified notice attachment of one inbox message.

    Vendor/company come from `resolve_ap_identity` (exact supplier or certified
    NIF, else exact sender domain). Certificates are vendor-wide tax status and apply to every company
    of the vendor. A bank letter is verified only when its sender domain equals
    the vendor master's email domain; otherwise verification is unknown.
    """
    doc_id, received_at = message["doc_id"], message["received_at"]
    receipt_key(received_at)
    source = f"inbox/ap/{doc_id}/message.json"
    events, diagnostics = [], []
    for facts, kind in documents:
        if kind not in KINDS:
            continue
        documents_seen = sorted({fact.evidence.document for values in facts.fields.values() for fact in values})
        label = f"{doc_id}/{documents_seen[0].rsplit('/', 1)[-1] if documents_seen else kind}"
        # The certified contractor's NIF identifies the vendor of a certificate.
        holder = facts.fields.get("supplier_tax_id") or facts.fields.get("certificate_tax_id", [])
        identity = resolve_ap_identity([DocumentFacts(facts.source_sha256, facts.extractor_version,
                                                      {**facts.fields, "supplier_tax_id": holder})], message, data)
        if identity.vendor_id is None:
            diagnostics.append(f"{label}:VENDOR_UNKNOWN")
            continue
        vendor = data.get("vendors", identity.vendor_id)
        companies = (list(vendor["companies"]) if kind == "CONTRACTOR_TAX_CERTIFICATE"
                     else [identity.company] if identity.company in vendor["companies"] else [])
        if not companies:
            diagnostics.append(f"{label}:COMPANY_UNKNOWN")
            continue
        from_names, until_names, value_names = FIELDS[kind]
        valid_from, from_proof = _one(facts, from_names, f"{label}:VALID_FROM", diagnostics, source_date)
        valid_until, until_proof = _one(facts, until_names, f"{label}:VALID_UNTIL", diagnostics, source_date)
        value, value_proof = _one(facts, value_names, f"{label}:VALUE", diagnostics)
        evidence = [Evidence(source, "received_at", quote=received_at), *identity.evidence,
                    *from_proof, *until_proof, *value_proof]
        verified = None
        if kind == "BANK_DETAILS_CHANGE":
            sender = _domain(message.get("from"))
            if sender is not None and sender == _domain(vendor.get("email")):
                verified = True
                evidence += [Evidence(source, "from", quote=message["from"]),
                             Evidence("erp/vendors.jsonl", f"id={vendor['id']}.email", quote=vendor["email"])]
        for company in companies:
            events.append(ApEvent(label, ApScope(company, vendor["id"], vendor["currency"]), kind,
                                  tuple(dict.fromkeys(evidence)), received_at=received_at,
                                  valid_from=valid_from, valid_until=valid_until,
                                  verified=verified, value=value))
    return NoticeBinding(tuple(events), tuple(diagnostics))


def invoice_events(data: PhaseData, scope: ApScope, notices: Iterable[ApEvent],
                   invoice_date: str, received_at: str, **options) -> InvoiceEventState:
    """ERP history (certificates, registered factor, garnishments) plus inbox notices.

    Ordering and tie-break are the engine's: reception, validity start, event ID
    (`doc_id/attachment`), so input order never changes the selected evidence.
    """
    return invoice_state((*registered_events(data, scope).events, *notices), scope,
                         invoice_date, received_at, data.month, **options)
