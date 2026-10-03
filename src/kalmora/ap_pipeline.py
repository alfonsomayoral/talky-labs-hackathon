"""Composition of evidenced AP stages; accounting rules remain in their engines."""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from calendar import monthrange
from datetime import date

from .ap_allocation import allocate_receipts
from .ap_duplicates import duplicate_result
from .ap_chronology import event_support_facts, receipt_key
from .ap_notice_bridge import strict_invoice_events
from .ap_erp import APERPBaseline
from .ap_line_source_bridge import APLineSourceBinding, validate_ap_line_sources
from .ap_holds import (
    HOLD_CODES, HoldScope, PriceLine, evaluate_holds, price_variance_check, receipt_quantity_check,
)
from .ap_output import APHeader, build_ap_row
from .ap_payment import resolve_payment
from .ap_rejections import (
    REJECTION_CODES, UNKNOWN, RuleCheck, RuleStage, bool_field, evaluate_ordered_checks,
    rejection_checks, resolve_field,
)
from .ap_transaction import APPostingInputs, APTransactionRequest, APTransactionState, commit_ap_transaction
from .facts import DocumentFacts, Evidence, Fact
from .model.ap_component_scope import APComponentScope
from .model.ap_duplicate_record import DuplicateRecord
from .model.ap_scope import ApScope
from .model.ap_timeline_state import ApTimelineState
from .money import decimal, integer

_AMOUNT_FIELDS = ("net_cents", "tax_cents", "gross_cents")
_ARITHMETIC_CODE = "ARITHMETIC_ERROR"


def source_rejection_stage(
    fields: Mapping[str, Sequence[Fact]], *, amount_sources: Sequence[DocumentFacts],
) -> RuleStage:
    """Apply rejection precedence while checking arithmetic within each source.

    ``fields`` contains the observed candidates and evidenced policy context used
    by the rejection engine. ``amount_sources`` are the independently normalized
    financial attachments, preserving their integer-cent observations and proof.
    Do not include a message or notice merely because it accompanies an invoice.

    Different totals across PDF/XML do not make either source arithmetically
    invalid. Keep those conflicting candidates for the comparison gate, and
    check net + charged tax = gross separately using the existing arithmetic
    rule. Missing amounts remain unknown; no candidate is selected or filled.
    """
    amount_sources = tuple(amount_sources)
    if any(not isinstance(source, DocumentFacts) for source in amount_sources):
        raise TypeError("arithmetic sources require normalized DocumentFacts")
    fields = dict(fields)
    # Context supplies applicability and master identities, not alternative
    # observations of printed deductions, addressee IDs or charged tax.
    # Retain both sides of any disagreement so an adapter cannot clear a gate
    # with a quota that contradicts the independently normalized attachments.
    for policy_name, source_name in (("withholding_cents", "withholding_cents"),
                                     ("recipient_nif", "recipient_tax_id"),
                                     ("charged_vat_cents", "tax_cents")):
        observed = tuple(f for source in amount_sources for f in source.fields.get(source_name, ()))
        if observed:
            context_facts = tuple(fields.get(policy_name, ()))
            if policy_name == "recipient_nif":
                # This gate checks presence; exact recipient identity is checked
                # separately. Existing source adapters use the PRESENT marker.
                # Preserve None/blank/invalid candidates rather than comparing
                # a presence marker to a literal tax identifier.
                def presence(fact):
                    value = "PRESENT" if isinstance(fact.value, str) and fact.value.strip() else fact.value
                    return Fact(value, fact.evidence)
                context_facts = tuple(map(presence, context_facts))
                observed = tuple(map(presence, observed))
            fields[policy_name] = (*context_facts, *observed)
    checks = list(rejection_checks(fields))
    arithmetic = []
    diagnostics = []
    for source in amount_sources:
        if not isinstance(source, DocumentFacts):
            raise TypeError("arithmetic sources require normalized DocumentFacts")
        source_fields = {name: source.fields.get(name, ()) for name in _AMOUNT_FIELDS}
        check = next(c for c in rejection_checks(source_fields) if c.code == _ARITHMETIC_CODE)
        arithmetic.append(check)
        diagnostics.extend(f"{source.source_sha256}:{note}" for note in check.diagnostics)
    violation = (True if any(c.violation is True for c in arithmetic) else
                 False if arithmetic and all(c.violation is False for c in arithmetic) else None)
    evidence = tuple(item for check in arithmetic for item in check.evidence)
    if not arithmetic:
        diagnostics.append("MISSING_ARITHMETIC_SOURCES")
    replacement = RuleCheck(_ARITHMETIC_CODE, violation, evidence, tuple(diagnostics))
    checks = tuple(replacement if c.code == _ARITHMETIC_CODE else c for c in checks)
    return evaluate_ordered_checks(checks, REJECTION_CODES, "REJECT")


@dataclass(frozen=True, kw_only=True)
class APInvoiceRequest:
    """Source observations and explicit policy context for one ordinary invoice.

    A request cannot authorize a POST. This coordinator decides eligibility and
    passes only a resolved decision to the real transactional factories. Empty
    context remains UNKNOWN; adapters must not manufacture non-applicability.
    """

    observation: DuplicateRecord
    duplicate_inventory_complete: Fact | None
    rejection_fields: Mapping[str, Sequence[Fact]]
    amount_sources: tuple[DocumentFacts, ...]
    hold_fields: Mapping[str, Sequence[Fact]]
    timeline: ApTimelineState = ApTimelineState()
    bank_event_fields: Mapping | None = None
    uncertain_event_kinds: tuple[str, ...] = ()
    incomplete_event_sources: tuple[str, ...] = ()
    construction_subcontractor: Fact | None = None
    event_inventory_evidence: Mapping[str, tuple[Evidence, ...]] | None = None
    invoice_date: Fact | None = None
    header: APHeader | None = None
    posting: APPostingInputs | None = None
    price_lines: tuple[PriceLine, ...] = ()
    quantity_evidence: tuple[Evidence, ...] = ()
    receipt_inventory_complete: Fact | None = None
    receipt_as_of: Fact | None = None
    guarantee_applicable: Fact | None = None
    source_payable_basis: Fact | None = None
    line_source_bindings: tuple[APLineSourceBinding, ...] = ()


@dataclass(frozen=True)
class APInvoiceResult:
    status: str  # DECIDED, COMMITTED, UNKNOWN; UNKNOWN is never an AP row
    row: dict | None
    state: APTransactionState
    evidence: tuple[Evidence, ...]
    stages: tuple[tuple[str, str], ...]
    diagnostics: tuple[str, ...] = ()
    checks: tuple[RuleCheck, ...] = ()
    observation: DuplicateRecord | None = None


def evaluate_ap_invoice(request: APInvoiceRequest, state: APTransactionState, *,
                        baseline: APERPBaseline, history: tuple[DuplicateRecord, ...] | None = None,
                        tax_catalog=None, withholding_catalog=None, rates=None, context=None) -> APInvoiceResult:
    """Compose duplicate → rejection → HOLD → payment → atomic posting.

    The active ERP baseline is mandatory. Quantity and price checks use a
    provisional real allocation; only a validated AP transaction publishes it.
    Unknown historical receipt capacity never proves shortage. No files, Golden,
    provider calls or mutable ERP changes occur at this boundary.
    """
    if not isinstance(request, APInvoiceRequest) or not isinstance(state, APTransactionState):
        raise TypeError("typed AP invoice request and transaction snapshot required")
    if not isinstance(baseline, APERPBaseline):
        raise TypeError("active-phase ERP baseline required")
    current = request.observation
    if not isinstance(current, DuplicateRecord) or current.document_type != "INVOICE":
        raise ValueError("ordinary invoice observation required")
    if receipt_key(current.received_at).strftime("%Y-%m") != baseline.month:
        raise ValueError("invoice reception differs from the active phase")
    if any(row["doc_id"] == current.doc_id for row in state.rows):
        raise ValueError("AP task already committed; replay starts from its saved phase baseline")
    used = {u.key: u.quantity_milli for u in state.consumption.usages}
    if (not set(baseline.history.consumption.invoices) <= set(state.consumption.invoices)
            or any(used.get(u.key, 0) < u.quantity_milli for u in baseline.history.consumption.usages)):
        raise ValueError("invoice state cannot discard the active ERP history")
    certainty_by_key = {c.receipt.key: c for c in baseline.history.certainties}
    if any(key not in certainty_by_key or certainty_by_key[key].consumed_milli is None for key in used):
        raise ValueError("invoice state cannot invent unknown historical receipt consumption")
    evidence = list(current.evidence)
    stages, checks = [], []

    def finish(status, row=None, diagnostics=(), new_state=state):
        observation = replace(current,
            status=row["decision"] if row is not None else "RECEIVED",
            duplicate_of=row.get("duplicate_of") if row is not None else None)
        return APInvoiceResult(status, row, new_state, tuple(dict.fromkeys(evidence)),
                               tuple(stages), tuple(diagnostics), tuple(checks), observation)

    def nonposting(decision, reason=None, original=None):
        row = build_ap_row(doc_id=current.doc_id, document_type="INVOICE", decision=decision,
                           reasons=() if reason is None else (reason,), header=request.header,
                           duplicate_of=original, context=context, tax_catalog=tax_catalog)
        return finish("DECIDED", row)

    if current.currency is None or current.amount_cents is None:
        stages.append(("duplicate", "UNKNOWN"))
        return finish("UNKNOWN", diagnostics=("CURRENT_IDENTITY_OR_AMOUNT_UNKNOWN",))

    complete = request.duplicate_inventory_complete
    if complete is not None:
        if not isinstance(complete, Fact) or type(complete.value) is not bool:
            raise TypeError("duplicate inventory completeness requires an explicit boolean Fact")
        evidence.append(complete.evidence)
    duplicates = (*baseline.duplicate_records, *state.observations, *(history or ()))
    covered = {(record.company, record.vendor, record.currency, record.doc_id,
                record.number, record.amount_cents, record.status, record.document_type)
               for record in duplicates if receipt_key(record.received_at).strftime("%Y-%m") == baseline.month
               and receipt_key(record.received_at) <= receipt_key(current.received_at)}
    if any((row["company"], row["vendor_id"], row["currency"], row["doc_id"],
            row["invoice_number"], row["gross"], row["decision"], row["document_type"]) not in covered
           for row in state.rows):
        return finish("UNKNOWN", diagnostics=("POSTED_DUPLICATE_OBSERVATIONS_INCOMPLETE",))
    # One observation must be backed by a complete independent header, never
    # by mixing fields across views. Conflicting other financial headers remain
    # available to the ordered CFDI rejection instead of disappearing in a
    # premature aggregate amount-consensus gate.
    header_supported, header_unknown = False, []
    for source in request.amount_sources:
        matches = True
        for name, value in (("document_number", current.number), ("currency", current.currency),
                            ("gross_cents", current.amount_cents)):
            source_value, proof, diagnostics = resolve_field(source.fields, name)
            evidence.extend(proof)
            if source_value is UNKNOWN or source_value is None:
                header_unknown.extend(diagnostics or (f"DUPLICATE_SOURCE_UNKNOWN:{name}",))
                matches = False
            elif type(source_value) is not type(value) or source_value != value:
                matches = False
        header_supported = header_supported or matches
    if not header_supported:
        if header_unknown or not request.amount_sources:
            return finish("UNKNOWN", diagnostics=tuple(header_unknown) or ("DUPLICATE_SOURCE_HEADER_UNKNOWN",))
        raise ValueError("duplicate observation differs from independent financial attachments")
    duplicate = duplicate_result(current, duplicates, inventory_complete=complete is not None and complete.value)
    evidence.extend(duplicate.evidence)
    stages.append(("duplicate", duplicate.status))
    if duplicate.status == "UNKNOWN":
        return finish("UNKNOWN", diagnostics=duplicate.diagnostics)
    if duplicate.status == "DUPLICATE":
        return nonposting("DUPLICATE", original=duplicate.duplicate_of)

    rejection = source_rejection_stage(request.rejection_fields, amount_sources=request.amount_sources)
    checks.extend(rejection.checks)
    evidence.extend(e for check in rejection.checks for e in check.evidence)
    stages.append(("rejection", rejection.status))
    if rejection.status == "UNKNOWN":
        return finish("UNKNOWN", diagnostics=tuple(d for c in rejection.checks if c.violation is None
                                                   for d in c.diagnostics))
    if rejection.status == "REJECT":
        return nonposting("REJECT", rejection.reason)

    for name in ("recipient_company", "order_company"):
        company, proof, _ = resolve_field(request.rejection_fields, name)
        evidence.extend(proof)
        if company is not UNKNOWN and company != current.company:
            raise ValueError("resolved identity/purchase company differs from invoice scope")

    if request.invoice_date is None:
        return finish("UNKNOWN", diagnostics=("CHRONOLOGY_INVOICE_DATE_UNKNOWN",))
    source_dates = {"document_date": tuple(f for source in request.amount_sources
                                           for f in source.fields.get("document_date", ()))}
    source_date, proof, diagnostics = resolve_field(source_dates, "document_date")
    evidence.extend(proof)
    if source_date is UNKNOWN or source_date is None:
        return finish("UNKNOWN", diagnostics=diagnostics or ("CHRONOLOGY_SOURCE_DATE_UNKNOWN",))
    if type(source_date) is not str or source_date != request.invoice_date.value:
        raise ValueError("chronology date differs from independent financial attachments")
    inventories = request.event_inventory_evidence or {}
    bank_value, _, _ = resolve_field(request.hold_fields, "invoice_bank_iban")
    chronology = strict_invoice_events(request.timeline, ApScope(current.company, current.vendor, current.currency),
        request.invoice_date.value, current.received_at, baseline.month, invoice_number=current.number,
        bank_iban=bank_value if isinstance(bank_value, str) else None, complete_kinds=tuple(inventories),
        inventory_evidence=inventories, bank_fields=request.bank_event_fields,
        uncertain_kinds=request.uncertain_event_kinds, incomplete_sources=request.incomplete_event_sources)
    support = event_support_facts(chronology.state, chronology.inventory_evidence)
    hold_fields = dict(request.hold_fields)
    for name in ("signed_change_supported", "factoring_supported"):
        hold_fields[name] = support[name]

    preliminary = evaluate_holds(hold_fields)
    early = evaluate_ordered_checks(preliminary.checks[:2], HOLD_CODES[:2], "HOLD")
    if early.status != "CLEAR":
        checks.extend(early.checks)
        evidence.extend(e for check in early.checks for e in check.evidence)
        stages.append(("hold", early.status))
        return (nonposting("HOLD", early.reason) if early.status == "HOLD" else
                finish("UNKNOWN", diagnostics=tuple(d for c in early.checks for d in c.diagnostics)))

    allocation = quantity_check = price_check = None
    quantity_applies, _, _ = bool_field(hold_fields, "quantity_check_applicable")
    price_applies, _, _ = bool_field(hold_fields, "price_check_applicable")
    inputs = request.posting
    if quantity_applies is True:
        if inputs is None or not inputs.quantity_lines or request.receipt_as_of is None:
            stages.append(("hold", "UNKNOWN"))
            return finish("UNKNOWN", diagnostics=("QUANTITY_POSTING_INPUTS_UNKNOWN",))
        linked = validate_ap_line_sources(bindings=request.line_source_bindings,
            amount_sources=request.amount_sources, valuation_lines=inputs.valuation_lines,
            quantity_lines=inputs.quantity_lines, currency=current.currency, amounts_required=False)
        evidence.extend(linked.evidence)
        if linked.status != "CLEAR":
            stages.append(("hold", "UNKNOWN"))
            return finish("UNKNOWN", diagnostics=linked.diagnostics)
        cutoff = request.receipt_as_of
        if not isinstance(cutoff, Fact) or not isinstance(cutoff.value, str):
            raise TypeError("receipt visibility requires a source-backed date Fact")
        cutoff_day = date.fromisoformat(cutoff.value)
        year, month = map(int, baseline.month.split("-"))
        if (cutoff_day.isoformat() != cutoff.value or cutoff.value != inputs.receipt_as_of
                or cutoff_day > date(year, month, monthrange(year, month)[1])
                or cutoff_day < receipt_key(current.received_at).date()):
            raise ValueError("receipt visibility differs from observed cutoff or active phase horizon")
        evidence.append(cutoff.evidence)
        if (inputs.order_catalog != baseline.orders or inputs.receipt_catalog != baseline.receipts
                or inputs.order_prices != baseline.prices):
            raise ValueError("quantity inputs must use the complete active ERP catalogue")
        certainty = {c.receipt.key: c for c in baseline.history.certainties}
        requested_orders = {p.order for line in inputs.quantity_lines for p in line.portions}
        for line in inputs.quantity_lines:
            for portion in line.portions:
                if portion.receipt_ids is None:
                    raise ValueError("quantity portions require evidenced eligible receipt IDs")
                for ident in portion.receipt_ids:
                    item = certainty.get((current.company, ident))
                    if item is not None and (item.consumed_milli is None or item.receipt.posting_date > inputs.receipt_as_of):
                        stages.append(("hold", "UNKNOWN"))
                        return finish("UNKNOWN", diagnostics=("RECEIPT_CAPACITY_OR_VISIBILITY_UNKNOWN",))
        allocation = allocate_receipts(company=current.company, vendor=current.vendor,
            currency=current.currency, invoice_id=current.doc_id, lines=inputs.quantity_lines,
            orders=inputs.order_catalog, receipts=inputs.receipt_catalog, state=state.consumption)
        if allocation.status != "ALLOCATED" and any(c.receipt.order in requested_orders
                and c.receipt.posting_date <= inputs.receipt_as_of and c.consumed_milli is None
                for c in baseline.history.certainties):
            stages.append(("hold", "UNKNOWN"))
            return finish("UNKNOWN", diagnostics=("HISTORICAL_RECEIPT_CAPACITY_UNKNOWN",))
        scope = HoldScope(current.company, current.vendor, current.currency, current.doc_id)
        quantity_check = receipt_quantity_check(scope, allocation, evidence=request.quantity_evidence,
                                                catalog_complete=request.receipt_inventory_complete)
        if price_applies is True and quantity_check.violation is False and request.invoice_date is not None:
            linked = validate_ap_line_sources(bindings=request.line_source_bindings,
                amount_sources=request.amount_sources, valuation_lines=inputs.valuation_lines,
                quantity_lines=inputs.quantity_lines, price_lines=request.price_lines,
                currency=current.currency, amounts_required=False)
            evidence.extend(linked.evidence)
            if linked.status != "CLEAR":
                stages.append(("hold", "UNKNOWN"))
                return finish("UNKNOWN", diagnostics=linked.diagnostics)
            actual_prices = {p.order: p.unit_price_cents for p in baseline.prices}
            prices = []
            for line in request.price_lines:
                portions = []
                for portion in line.portions:
                    price = actual_prices.get(portion.order)
                    if price is None or any(f.value is None or decimal(f.value) != decimal(price)
                                           for f in portion.po_unit_price_cents):
                        raise ValueError("price check candidates differ from the active ERP PO price")
                    proof = Evidence("erp/purchase_orders.jsonl",
                        f"id={portion.order.po}.items[{portion.order.item}].unit_price")
                    portions.append(replace(portion, po_unit_price_cents=(Fact(price, proof),)))
                prices.append(replace(line, portions=tuple(portions)))
            price_check = price_variance_check(scope, request.invoice_date, tuple(prices),
                allocation=allocation, rates=rates,
                rate_evidence=(Evidence("erp/fx_rates.jsonl", "invoice-date EUR threshold"),))
    elif quantity_applies is False and inputs is not None and inputs.quantity_lines:
        raise ValueError("quantity non-applicability conflicts with PO quantity lines")
    hold = evaluate_holds(hold_fields, quantity_check=quantity_check, price_check=price_check)
    checks.extend(hold.checks)
    evidence.extend(e for check in hold.checks for e in check.evidence)
    stages.append(("hold", hold.status))
    if hold.status == "UNKNOWN":
        return finish("UNKNOWN", diagnostics=tuple(d for c in hold.checks if c.violation is None for d in c.diagnostics))
    if hold.status == "HOLD":
        return nonposting("HOLD", hold.reason)

    construction = request.construction_subcontractor
    if construction is not None:
        if not isinstance(construction, Fact) or type(construction.value) is not bool:
            raise TypeError("subcontractor applicability requires an explicit boolean Fact")
        evidence.append(construction.evidence)
    payment = resolve_payment(duplicate.status, rejection.status, hold.status,
        construction.value if construction is not None else None, chronology.state,
        inventory_evidence=chronology.inventory_evidence)
    evidence.extend(payment.evidence)
    stages.append(("payment", payment.decision))
    if payment.decision == "UNKNOWN":
        return finish("UNKNOWN", diagnostics=payment.diagnostics)
    if inputs is None or request.invoice_date is None:
        return finish("UNKNOWN", diagnostics=("MONETARY_POSTING_INPUTS_UNKNOWN",))
    linked = validate_ap_line_sources(bindings=request.line_source_bindings,
        amount_sources=request.amount_sources, valuation_lines=inputs.valuation_lines,
        quantity_lines=inputs.quantity_lines, currency=current.currency)
    evidence.extend(linked.evidence)
    if linked.status != "CLEAR":
        return finish("UNKNOWN", diagnostics=linked.diagnostics)
    header = inputs.header
    if (header.company, header.vendor_id, header.currency, header.invoice_number, header.gross) != (
            current.company, current.vendor, current.currency, current.number, current.amount_cents):
        raise ValueError("posting header differs from source duplicate observation")
    if header.invoice_date != request.invoice_date.value:
        raise ValueError("posting invoice date differs from source observation")
    evidence.append(request.invoice_date.evidence)
    for name, value in (("net_cents", header.net), ("tax_cents", header.tax), ("gross_cents", header.gross)):
        observed, proof, diagnostics = resolve_field(request.rejection_fields, name)
        evidence.extend(proof)
        if observed is UNKNOWN:
            return finish("UNKNOWN", diagnostics=diagnostics)
        if observed != value or type(observed) is not int:
            raise ValueError("posting amounts differ from independent source facts")
        source_candidates = {name: tuple(f for source in request.amount_sources for f in source.fields.get(name, ()))}
        source_value, proof, source_diagnostics = resolve_field(source_candidates, name)
        evidence.extend(proof)
        if source_value is UNKNOWN:
            return finish("UNKNOWN", diagnostics=source_diagnostics)
        if source_value != value or type(source_value) is not int:
            raise ValueError("posting amounts differ from independent financial attachments")
    for name, value in (("document_number", header.invoice_number),
                        ("document_date", header.invoice_date), ("currency", header.currency)):
        candidates = {name: tuple(f for source in request.amount_sources for f in source.fields.get(name, ()))}
        source_value, proof, diagnostics = resolve_field(candidates, name)
        evidence.extend(proof)
        if source_value is UNKNOWN or source_value is None:
            return finish("UNKNOWN", diagnostics=diagnostics or (f"SOURCE_HEADER_UNKNOWN:{name}",))
        if type(source_value) is not str or source_value != value:
            raise ValueError("posting identity/date/currency differ from independent financial attachments")

    # Printed deductions are observations, not optional hints. Calculated
    # deductions are checked again by the transactional journal/output engines.
    for name, value in (("withholding_cents", header.withholding), ("retention_cents", header.retention)):
        aliases = (name, "guarantee_amount_cents") if name == "retention_cents" else (name,)
        candidates = tuple(f for source in request.amount_sources for alias in aliases
                           for f in source.fields.get(alias, ()))
        if candidates:
            observed, proof, diagnostics = resolve_field({name: candidates}, name)
            evidence.extend(proof)
            if observed is UNKNOWN or observed is None:
                return finish("UNKNOWN", diagnostics=diagnostics or (f"SOURCE_DEDUCTION_UNKNOWN:{name}",))
            if type(observed) is not int or observed != value:
                raise ValueError("posting deductions differ from independent financial attachments")

    guarantee = request.guarantee_applicable
    if guarantee is None or not isinstance(guarantee, Fact) or type(guarantee.value) is not bool:
        return finish("UNKNOWN", diagnostics=("GUARANTEE_APPLICABILITY_UNKNOWN",))
    evidence.append(guarantee.evidence)
    if guarantee.value and inputs.guarantee is None:
        return finish("UNKNOWN", diagnostics=("GUARANTEE_CONTRACT_UNKNOWN",))
    if not guarantee.value and (inputs.guarantee is not None or header.retention != 0):
        raise ValueError("guarantee non-applicability conflicts with posting retention")

    payable_candidates = tuple(f for source in request.amount_sources for f in source.fields.get("payable_cents", ()))
    if payable_candidates:
        observed, proof, diagnostics = resolve_field({"payable_cents": payable_candidates}, "payable_cents")
        evidence.extend(proof)
        if observed is UNKNOWN or observed is None:
            return finish("UNKNOWN", diagnostics=diagnostics or ("SOURCE_PAYABLE_UNKNOWN",))
        basis = request.source_payable_basis
        if (not isinstance(basis, Fact)
                or basis.value not in {"BEFORE_APPLIED_ADVANCES", "AFTER_APPLIED_ADVANCES"}):
            return finish("UNKNOWN", diagnostics=("SOURCE_PAYABLE_BASIS_UNKNOWN",))
        evidence.append(basis.evidence)
        expected = header.payable
        if basis.value == "BEFORE_APPLIED_ADVANCES":
            expected += sum(integer(a.amount_doc, "applied advance document cents") for a in inputs.advances)
        if type(observed) is not int or observed != expected:
            raise ValueError("posting payable differs from the evidenced printed payable basis")
    guard = baseline.posting_guard(company=current.company, vendor=current.vendor,
        currency=current.currency, doc_id=current.doc_id, number=current.number)
    evidence.extend(guard.evidence)
    if guard.status != "CLEAR":
        return finish("UNKNOWN", diagnostics=guard.diagnostics or (guard.status,))
    if inputs.payee is not None or inputs.payment_block is not None:
        raise ValueError("payment metadata must come from the policy result")
    inputs = replace(inputs, payee={"type": payment.payee} if payment.payee else None,
                     payment_block=payment.payment_block)
    posting_scope = APComponentScope(current.company, current.vendor, current.currency,
                                     current.doc_id, header.invoice_date, payment.decision)
    transaction = commit_ap_transaction(APTransactionRequest(scope=posting_scope, document_type="INVOICE",
        evidence=tuple(dict.fromkeys(evidence)), posting=inputs,
        observation=replace(current, status=payment.decision)), state, tax_catalog=tax_catalog,
        withholding_catalog=withholding_catalog, rates=rates, context=context)
    stages.append(("posting", transaction.status))
    if transaction.status != "COMMITTED":
        return finish("UNKNOWN", diagnostics=tuple(d.code for d in transaction.diagnostics))
    return finish("COMMITTED", transaction.row, new_state=transaction.state)
