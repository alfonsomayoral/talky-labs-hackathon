"""Tentative credit restoration; no ledger, publication or allocator mutation."""
from dataclasses import dataclass, replace
from datetime import date
from collections.abc import Mapping

from .ap_allocation import ConsumptionState, QuantityAllocation, Receipt, ReceiptUsage
from .ap_credit_state import original_credit_sha256
from .ap_journal import APJournalResult, build_ap_journal
from .facts import Evidence, Fact


@dataclass(frozen=True)
class ReceiptRestoration:
    credit_line_id: Fact
    original_invoice_id: Fact
    quantity_milli: Fact
    original_entry: Mapping
    receipt: Receipt
    original_allocation: QuantityAllocation
    allocation_evidence: Evidence
    original_invoice: Mapping | None = None
    invoice_evidence: Evidence | None = None
    allocation_invoice_id: Fact | None = None


@dataclass(frozen=True)
class RestoredReceiptUsage:
    company: str
    original_invoice_id: str
    original_sha256: str
    original_line_id: str
    receipt_id: str
    capacity_milli: int
    used_milli: int


@dataclass(frozen=True)
class ReceiptRestorationState:
    usages: tuple[RestoredReceiptUsage, ...] = ()


@dataclass(frozen=True)
class TentativeCreditRestoration:
    journal: APJournalResult
    consumption: ConsumptionState
    restoration_state: ReceiptRestorationState
    evidence: tuple[Evidence, ...]


def prepare_ap_credit_restoration(*, journal_arguments: Mapping,
                                  consumption: ConsumptionState,
                                  receipt_restorations: tuple[ReceiptRestoration, ...] = (),
                                  restoration_state: ReceiptRestorationState = ReceiptRestorationState()) -> TentativeCreditRestoration:
    """Build the real credit journal and tentatively release explicit receipt usage.

    Caller validates its real AP row before publishing any of these snapshots.
    If journal, receipt evidence or subsequent header/output validation fails,
    discard the result: input snapshots remain intact. Receipt restoration is
    never inferred from credited money or an original GR/IR balance. A sidecar
    retains per-original restored quantities, so another invoice's consumption
    cannot fund repeated restoration of this original receipt allocation.
    """
    arguments = dict(journal_arguments)
    if arguments.get("document_type") != "CREDIT_NOTE":
        raise ValueError("credit restoration requires explicit CREDIT_NOTE")
    references = tuple(arguments.get("credit_references", ()))
    arguments["credit_references"] = references
    journal = build_ap_journal(**arguments)
    company, vendor, currency = arguments["company"], arguments["vendor"], arguments["currency"]
    usages = {usage.key: usage for usage in consumption.usages}
    if len(usages) != len(consumption.usages):
        raise ValueError("unique committed receipt usages required")
    previous = {}
    for usage in restoration_state.usages:
        key = (usage.company, usage.original_invoice_id, usage.original_line_id, usage.receipt_id)
        if key in previous or type(usage.used_milli) is not int or type(usage.capacity_milli) is not int or not 0 <= usage.used_milli <= usage.capacity_milli:
            raise ValueError("invalid cumulative receipt restoration state")
        previous[key] = usage
    proof, seen = [], set()
    for request in receipt_restorations:
        if not isinstance(request, ReceiptRestoration):
            raise TypeError("evidenced original receipt restoration required")
        facts = (request.credit_line_id, request.original_invoice_id, request.quantity_milli)
        if not all(isinstance(fact, Fact) for fact in facts) or not isinstance(request.allocation_evidence, Evidence):
            raise TypeError("receipt restoration requires Fact/Evidence")
        if len({fact.evidence.document for fact in facts}) != 1:
            raise ValueError("restored quantity/original/credit line must identify one source statement")
        line_id, original_id, quantity = (fact.value for fact in facts)
        if (not isinstance(line_id, str) or not line_id or not isinstance(original_id, str) or not original_id
                or type(quantity) is not int or quantity <= 0):
            raise ValueError("explicit restored quantity and original/credit line required")
        invoice = request.original_invoice
        if (not isinstance(invoice, Mapping) or not isinstance(request.invoice_evidence, Evidence)
                or (invoice.get("company"), invoice.get("vendor"), invoice.get("currency"), invoice.get("doc_id"),
                    invoice.get("journal_entry"), invoice.get("number"), invoice.get("issue_date"), invoice.get("kind")) !=
                   (company, vendor, currency, original_id, request.original_entry.get("id"),
                    request.original_entry.get("reference"), request.original_entry.get("document_date"), "invoice")):
            raise ValueError("original receipt invoice must corroborate the exact AP-to-GL link")
        if (not isinstance(request.allocation_invoice_id, Fact) or request.allocation_invoice_id.value != original_id
                or request.allocation_invoice_id.evidence.document != request.allocation_evidence.document):
            raise ValueError("original receipt allocation must explicitly identify the same AP invoice")
        receipt, allocation = request.receipt, request.original_allocation
        if not isinstance(receipt, Receipt) or not isinstance(allocation, QuantityAllocation):
            raise TypeError("recorded receipt and original allocation required")
        if ((receipt.order.company, receipt.order.vendor, receipt.order.currency) != (company, vendor, currency)
                or allocation.order != receipt.order or allocation.receipt_id != receipt.receipt_id
                or type(allocation.quantity_milli) is not int or allocation.quantity_milli <= 0
                or type(receipt.quantity_milli) is not int or receipt.quantity_milli <= 0
                or allocation.quantity_milli > receipt.quantity_milli
                or (company, vendor, currency, original_id) not in consumption.invoices):
            raise ValueError("original receipt allocation scope/capacity unresolved")
        try:
            valid_receipt_date = date.fromisoformat(receipt.posting_date).isoformat() == receipt.posting_date
        except (ValueError, TypeError):
            valid_receipt_date = False
        if not valid_receipt_date or receipt.posting_date > request.original_entry.get("posting_date", ""):
            raise ValueError("original receipt must predate the original invoice posting")
        refs = [reference for reference in references if reference.line_id == line_id
                and reference.original_entry == request.original_entry]
        if not refs or request.original_entry.get("company") != company:
            raise ValueError("restoration must bind the same credited original invoice")
        assignment = f"{receipt.order.po}/{receipt.order.item}"
        indexes = set(number for reference in refs for number in
                      (reference.original_lines or (reference.original_line,)))
        if not any(line.get("line", index) in indexes and line.get("assignment") == assignment
                   and line.get("account") == "40090000" and line.get("partner") == vendor
                   for index, line in enumerate(request.original_entry["lines"], 1)):
            raise ValueError("original receipt allocation lacks referenced GR/IR PO position")
        digest = original_credit_sha256(dict(request.original_entry))
        key = (company, original_id, allocation.line_id, receipt.receipt_id)
        if key in seen:
            raise ValueError("duplicate original receipt restoration")
        seen.add(key)
        old = previous.get(key, RestoredReceiptUsage(company, original_id, digest, allocation.line_id,
                                                     receipt.receipt_id, allocation.quantity_milli, 0))
        if old.original_sha256 != digest or old.capacity_milli != allocation.quantity_milli:
            raise ValueError("original receipt restoration snapshot/capacity changed")
        current = usages.get(receipt.key)
        if (current is None or current.order != receipt.order or type(current.quantity_milli) is not int
                or current.quantity_milli < quantity or old.used_milli + quantity > old.capacity_milli):
            raise ValueError("restored quantity exceeds original or committed receipt usage")
        usages[receipt.key] = replace(current, quantity_milli=current.quantity_milli - quantity)
        previous[key] = replace(old, used_milli=old.used_milli + quantity)
        proof.extend((*[fact.evidence for fact in facts], request.allocation_evidence,
                      request.invoice_evidence, request.allocation_invoice_id.evidence))
    tentative = ConsumptionState(tuple(usages[key] for key in sorted(usages) if usages[key].quantity_milli), consumption.invoices)
    return TentativeCreditRestoration(journal, tentative, ReceiptRestorationState(tuple(previous[key] for key in sorted(previous))),
                                      tuple(dict.fromkeys(proof)))
