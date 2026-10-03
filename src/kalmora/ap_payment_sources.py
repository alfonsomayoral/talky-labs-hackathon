"""Bind chronology-bound notices and invoice scope to the payment engine (#50).

Notice events come from `ap_chronology_sources.notice_events` (#46) and scope
from the identity binding (#42). No extraction, posting or ERP writes; absent or
contradictory facts stay unknown and the engines decide.
"""
from collections.abc import Iterable
from datetime import date
import re

from .ap_chronology import KINDS
from .ap_chronology_sources import invoice_events
from .ap_payment import apply_notice, resolve_payment
from .data import PhaseData
from .documents.classification import TITLE_RULES, _title
from .documents.normalization import NormalizedDocument
from .facts import Evidence
from .model.ap_event import ApEvent
from .model.ap_notice_resolution import NoticeResolution
from .model.ap_payment_resolution import PaymentResolution
from .model.ap_scope import ApScope
from .model.ap_timeline_state import ApTimelineState


def resolve_notice(document_type: str, events: Iterable[ApEvent],
                   state: ApTimelineState = ApTimelineState()) -> NoticeResolution:
    """NOT_INVOICE action; registers the message's events (one per company)."""
    events = tuple(events)
    if document_type not in KINDS or not events:
        return apply_notice(document_type, state=state)
    for event in events:
        result = apply_notice(document_type, event, state)
        state = result.state
    return result


def possible_notice_kinds(subject: str | None) -> tuple[str, ...]:
    """Kinds an unclassified or unbound document may hide, from its literal subject.

    A subject naming only other document types hides none; no recognizable title
    could hide any notice.
    """
    title = _title(subject) if isinstance(subject, str) else ""
    found = {kind for kind, pattern in TITLE_RULES if re.search(rf"\b(?:{pattern})\b", title)}
    if re.search(r"\b(?:fra|factura\w*)\b", title):  # "FRA", "facturación": invoicing subjects
        found.add("INVOICE")
    return tuple(kind for kind in KINDS if kind in found) or (() if found else KINDS)


def invoice_date_candidates(documents: Iterable[NormalizedDocument]) -> set[str]:
    """Normalized invoice dates plus both readings of a day/month-ambiguous one."""
    documents = tuple(documents)
    dates = {fact.value for document in documents
             for fact in document.facts.fields.get("document_date", ()) if fact.value}
    for diagnostic in (d for document in documents for d in document.diagnostics):
        if diagnostic.field in ("document_date", "invoice_date") and "day/month" in diagnostic.message:
            for fact in diagnostic.evidence:
                first, second, year = map(int, re.findall(r"\d+", fact.value))
                dates |= {date(year, second, first).isoformat(), date(year, first, second).isoformat()}
    return dates


def resolve_invoice_payment(*, data: PhaseData, scope: ApScope, invoice_dates: Iterable[str], received_at: str,
                            notices: Iterable[ApEvent], complete_kinds: Iterable[str],
                            duplicate_status: str, rejection_status: str,
                            hold_status: str) -> PaymentResolution:
    """Payment block/payee from ERP baselines plus the month's registered notices.

    `complete_kinds` are the kinds for which every inbox document received by the
    invoice was classified and bound, so absence there is proved; others stay unknown.
    Construction subcontractors are the vendors whose master default is ISP de obra.
    """
    complete, notices, dates = tuple(complete_kinds), tuple(notices), sorted(invoice_dates)
    if not dates:
        return PaymentResolution("UNKNOWN", diagnostics=("INVOICE_DATE_UNKNOWN",))
    results = [_payment(data, scope, invoice_date, received_at, notices, complete,
                        duplicate_status, rejection_status, hold_status) for invoice_date in dates]
    # Candidate dates (conflicting or day/month ambiguous) count only if irrelevant.
    if len({(r.decision, r.payment_block, r.payee) for r in results}) > 1:
        return PaymentResolution("UNKNOWN", diagnostics=("INVOICE_DATE_UNKNOWN",))
    return results[0]


def _payment(data, scope, invoice_date, received_at, notices, complete,
             duplicate_status, rejection_status, hold_status) -> PaymentResolution:
    observed = invoice_events(data, scope, notices, invoice_date, received_at, complete_kinds=complete)
    tables = dict(zip(KINDS, ("erp/contractor_certificates.jsonl", "erp/vendors.jsonl",
                              "erp/vendors.jsonl", "erp/vendors.jsonl")))
    inventories = {kind: (Evidence(tables[kind], f"vendor={scope.vendor}"),
                          Evidence("inbox/ap", f"{kind} documents received by {received_at}"))
                   for kind in complete}
    tax_code = data.get("vendors", scope.vendor).get("default_tax_code")
    return resolve_payment(duplicate_status, rejection_status, hold_status,
                           None if tax_code is None else tax_code == "SISP", observed,
                           inventory_evidence=inventories)
