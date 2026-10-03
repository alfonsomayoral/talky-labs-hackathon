"""Complete AP journals from resolved monetary components, without extraction.

Advance/posted-event state is tentative: commit it only after successful ledger
posting. Sources: policies §1/§2.1/§2.3 and original AP import history.
"""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal
import re

from .ap_tax import PostingDecision, TaxResult, fiscal_line, local_amount, nonnegative, require_posting
from .ap_valuation import CostAssignment, ValuationResult
from .ap_withholding import WithholdingResult
from .model.journal_entry import JournalEntry
from .model.journal_line import JournalLine
from .model.validation_context import ValidationContext
from .model.ap_component_scope import APComponentScope
from .money import RateTable, company_local_currency, integer
from .validation import validate_entry


@dataclass(frozen=True)
class AdvanceBalance:
    advance_id: str
    company: str
    vendor: str
    currency: str
    invoice_number: str
    original_date: str
    po: str
    amount_doc: int
    amount_local: int
    used_doc: int = 0
    used_local: int = 0


@dataclass(frozen=True)
class AdvanceState:
    balances: tuple[AdvanceBalance, ...] = ()
    events: tuple[tuple[str, str, str, str], ...] = ()


@dataclass(frozen=True)
class AdvanceApplication:
    advance_id: str
    amount_doc: int
    treatment: Literal["NON_MONETARY", "MONETARY"] | None = None
    treatment_reference: str | None = None
    cost_assignment: CostAssignment | None = None
    line_id: str | None = None


@dataclass(frozen=True)
class InvoiceLineOrder:
    line_id: str
    po: str
    base_doc: int
    reference: str


@dataclass(frozen=True)
class AdvanceUsage:
    advance_id: str
    amount_doc: int
    historical_local: int
    invoice_local: int
    treatment: Literal["NON_MONETARY", "MONETARY"]
    treatment_reference: str


@dataclass(frozen=True)
class CreditReference:
    line_id: str
    original_entry: JournalEntry
    original_line: int


@dataclass(frozen=True)
class ApprovedAdvanceOrder:
    company: str
    vendor: str
    currency: str
    po: str
    approved: bool | None
    approval_reference: str | None


@dataclass(frozen=True)
class APJournalResult:
    document_type: str
    payable_doc: int
    payable_local: int
    journal_entry: JournalEntry
    state: AdvanceState
    advance_usages: tuple[AdvanceUsage, ...] = ()


def _text(value: str | None, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"resolved {name} required")


def _ratio(amount: int, numerator: int, denominator: int) -> int:
    """Exact half-up positive rational cents, without a rounded residual rate."""
    return (2 * amount * numerator + denominator) // (2 * denominator)


def _state(state: AdvanceState) -> dict[tuple[str, str], AdvanceBalance]:
    balances: dict[tuple[str, str], AdvanceBalance] = {}
    for balance in state.balances:
        for name in ("advance_id", "vendor", "currency", "invoice_number", "original_date", "po"):
            _text(getattr(balance, name), name)
        local_amount(0, balance.company, company_local_currency(balance.company), balance.original_date, None)
        key = (balance.company, balance.advance_id)
        if key in balances:
            raise ValueError("duplicate advance within company")
        original_doc = nonnegative(balance.amount_doc, "original advance document amount")
        original_local = nonnegative(balance.amount_local, "original advance carrying amount")
        if (not re.fullmatch("[A-Z]{3}", balance.currency)
                or (balance.currency == company_local_currency(balance.company) and original_doc != original_local)):
            raise ValueError("advance document/local currency amounts are inconsistent")
        used_doc = nonnegative(balance.used_doc, "consumed advance document amount")
        used_local = nonnegative(balance.used_local, "consumed advance carrying amount")
        if (not original_doc or used_doc > original_doc or used_local > original_local
                or used_local != _ratio(original_local, used_doc, original_doc)):
            raise ValueError("invalid historical advance consumption")
        balances[key] = balance
    if len(set(state.events)) != len(state.events):
        raise ValueError("duplicate posted document in tentative state")
    for event in state.events:
        if len(event) != 4:
            raise ValueError("invalid posted document scope")
        for value in event:
            _text(value, "posted document scope")
    return balances


def _scope(*, company: str, vendor: str, currency: str, invoice_date: str,
           posting_date: str, invoice_number: str, doc_id: str, decision: PostingDecision,
           rates: RateTable | None, state: AdvanceState) -> tuple[dict[tuple[str, str], AdvanceBalance], tuple[str, str, str, str]]:
    require_posting(decision)
    for value, name in ((vendor, "vendor"), (invoice_number, "invoice number"), (doc_id, "document id")):
        _text(value, name)
    local_amount(0, company, currency, invoice_date, rates)
    local_amount(0, company, company_local_currency(company), posting_date, None)
    balances = _state(state)
    event = (company, vendor, currency, doc_id)
    if event in state.events:
        raise ValueError("document already posted in tentative state")
    return balances, event


def _entry(company: str, currency: str, invoice_number: str, invoice_date: str,
           posting_date: str, lines: list[JournalLine], document_type: str,
           context: ValidationContext | None) -> JournalEntry:
    if any(not line["debit"] and not line["credit"] and line.get("amount_doc", 0) for line in lines):
        raise ValueError("positive document amount has no representable local debit/credit side")
    entry: JournalEntry = {"company": company, "currency": currency, "reference": invoice_number,
                           "document_date": invoice_date, "posting_date": posting_date, "source": "AP",
                           "doc_type": "KG" if document_type == "CREDIT_NOTE" else "KR",
                           "lines": [dict(line) for line in lines if line["debit"] or line["credit"]]}
    errors = validate_entry(entry, context)
    if errors:
        raise ValueError("invalid AP journal: " + "; ".join(errors))
    return entry


def _credit_imputation(*, company: str, vendor: str, currency: str, reconciliation_account: str,
                       invoice_date: str, valuation: ValuationResult, tax: TaxResult,
                       withholding: WithholdingResult, references: Iterable[CreditReference]) -> None:
    references = tuple(references)
    if not references:
        raise ValueError("credit notes require resolved original imputation evidence")
    candidates: dict[str, list[tuple[tuple[str, str, int], JournalLine]]] = {}
    originals: dict[str, JournalEntry] = {}
    seen_refs: set[tuple[str, tuple[str, str, int]]] = set()
    for ref in references:
        _text(ref.line_id, "credited line id")
        original = ref.original_entry
        if validate_entry(original) or original.get("company") != company or not original.get("id"):
            raise ValueError("invalid original credit-note journal evidence")
        if (original.get("doc_type") != "KR" or not original.get("document_date")
                or original["document_date"] > invoice_date):
            raise ValueError("credit original must identify an existing earlier invoice")
        _text(original["id"], "original journal id")
        if original["id"] in originals and originals[original["id"]] != original:
            raise ValueError("conflicting original journal evidence")
        originals[original["id"]] = original
        if not any(l["account"] == reconciliation_account and l.get("partner") == vendor for l in original["lines"]):
            raise ValueError("credit original belongs to another vendor/reconciliation account")
        if any(l["account"].startswith("407") and (l["debit"] or l["credit"])
               for l in original["lines"]):
            raise ValueError("credit original contains applied advances; restoration requires resolved evidence")
        number = integer(ref.original_line, "original line number")
        matches = [l for i, l in enumerate(original["lines"], 1) if l.get("line", i) == number]
        if len(matches) != 1 or matches[0].get("currency", original.get("currency")) != currency:
            raise ValueError("original credited line/currency unresolved")
        key = (company, original["id"], number)
        if (ref.line_id, key) in seen_refs:
            raise ValueError("duplicate original credit mapping")
        seen_refs.add((ref.line_id, key))
        candidates.setdefault(ref.line_id, []).append((key, matches[0]))
    credited: dict[tuple[str, str, int], int] = {}
    line_original: dict[str, str] = {}
    for component in valuation.components:
        matches = [(key, l) for key, l in candidates.get(component.line_id, ())
                   if (l["account"], l.get("partner"), l.get("cost_center"), l.get("wbs")) ==
                   (component.account, component.partner, component.cost_center, component.wbs)
                   and (component.order is None or l.get("assignment") == f"{component.order.po}/{component.order.item}")
                   and ((component.amount_doc > 0) == (l["debit"] > l["credit"]))]
        if len(matches) != 1:
            raise ValueError("credit-note original imputation is missing or ambiguous")
        key, line = matches[0]
        if component.line_id in line_original and line_original[component.line_id] != key[1]:
            raise ValueError("credited fiscal line spans ambiguous original invoices")
        line_original[component.line_id] = key[1]
        credited[key] = credited.get(key, 0) + abs(component.amount_doc)
        if credited[key] > line.get("amount_doc", max(line["debit"], line["credit"])):
            raise ValueError("aggregate credit exceeds referenced original line")
    fiscal_original: dict[str, str] = {}
    fiscal_by_original: dict[str, list] = {}
    requested_vat: dict[tuple[str, str], int] = {}
    for component in tax.components:
        refs = candidates.get(component.line_id, ())
        entries = {key[1] for key, _ in refs}
        if len(entries) != 1:
            raise ValueError("credit-note fiscal treatment requires unambiguous original evidence")
        original_id = next(iter(entries))
        original = originals[original_id]
        codes = {l.get("tax_code") for _, l in refs if l.get("tax_code")}
        if not codes:
            observed_net_codes = {l.get("tax_code") for l in original["lines"]
                                  if l["account"][0] in "26" and l.get("tax_code")}
            codes = {l.get("tax_code") for l in original["lines"]
                     if l["account"] in {"47200000", "47210000"} and l.get("tax_code")}
            if observed_net_codes - codes:
                raise ValueError("unlabelled original base has mixed fiscal treatment")
        if codes != {component.tax_code}:
            raise ValueError("credit-note tax treatment differs from original or is unknown")
        fiscal_original[component.line_id] = original_id
        fiscal_by_original.setdefault(original_id, []).append(component)
        if component.tax_code == "SIMP" and not any(l["account"] == "47200000" and l.get("tax_code") == "SIMP" for _, l in refs):
            raise ValueError("DUA credit requires explicit original DUA line reference")
        quota = sum(l["amount_doc"] for l in component.journal_lines if l["account"] in {"47200000", "47210000"})
        key = (original_id, component.tax_code)
        requested_vat[key] = requested_vat.get(key, 0) + quota
    for (original_id, code), amount in requested_vat.items():
        original_quota = sum(l.get("amount_doc", l["debit"]) for l in originals[original_id]["lines"]
                             if l["account"] in {"47200000", "47210000"} and l.get("tax_code") == code)
        if amount > original_quota:
            raise ValueError("credit VAT exceeds original fiscal quota")
    for component in tax.components:
        original_id = fiscal_original[component.line_id]
        for posting in component.journal_lines:
            if not posting["account"].startswith(("2", "6")):
                continue
            dimension = (posting["account"], posting.get("cost_center"), posting.get("wbs"))
            original_cost = sum(l.get("amount_doc", max(l["debit"], l["credit"])) *
                                (1 if l["debit"] > l["credit"] else -1)
                                for l in originals[original_id]["lines"]
                                if (l["account"], l.get("cost_center"), l.get("wbs")) == dimension
                                and l.get("currency", currency) == currency)
            net_credit = sum(c.amount_doc for c in valuation.components
                             if line_original.get(c.line_id) == original_id
                             and (c.account, c.cost_center, c.wbs) == dimension)
            tax_credit = sum(l["amount_doc"] for c in tax.components
                             if fiscal_original[c.line_id] == original_id for l in c.journal_lines
                             if (l["account"], l.get("cost_center"), l.get("wbs")) == dimension)
            if net_credit + tax_credit > original_cost:
                raise ValueError("non-deductible credit cost exceeds original expense/asset")
    # Check deductions against observed original treatments and catalogue bases,
    # not today's vendor defaults. Unknown/mixed original allocation abstains.
    catalog = dict(withholding.catalog_codes)
    expected: dict[tuple[str, str], int] = {}
    guarantee_base = 0
    for original_id, fiscal in fiscal_by_original.items():
        original = originals[original_id]
        net_lines = [l for l in original["lines"]
                     if ((l["account"][0] in "26" and l["account"] not in {"66800000", "76800000"})
                         or l["account"] == "40090000") and l.get("currency", currency) == currency]
        net = sum(l.get("amount_doc", max(l["debit"], l["credit"])) * (1 if l["debit"] > l["credit"] else -1) for l in net_lines)
        original_withholding = [l for l in original["lines"] if l["account"] == "47510000" and l["credit"]]
        taxable_lines = [l for l in net_lines if l.get("tax_code") in {"S21", "P23", "M16"}]
        taxable = sum(l.get("amount_doc", l["debit"]) * (1 if l["debit"] > l["credit"] else -1) for l in taxable_lines)
        for line in original_withholding:
            code = line.get("tax_code")
            treatment = catalog.get(code)
            if treatment is None or line["account"] != treatment.account:
                raise ValueError("original withholding treatment is unknown")
            if _ratio(taxable, treatment.rate, 10000) != line.get("amount_doc", line["credit"]):
                raise ValueError("original withholding base allocation is unresolved")
            for component in fiscal:
                if component.tax_code in {"S21", "P23", "M16"}:
                    key = (component.line_id, code)
                    expected[key] = _ratio(component.base_doc, treatment.rate, 10000)
        original_guarantee = sum(l.get("amount_doc", l["credit"]) for l in original["lines"] if l["account"] == "40000900" and l["credit"])
        if original_guarantee:
            if _ratio(net, 500, 10000) != original_guarantee:
                raise ValueError("original guarantee eligible base is unresolved")
            guarantee_base += sum(c.base_doc for c in fiscal)
    actual: dict[tuple[str, str], int] = {}
    for component in withholding.components:
        if component.kind == "WITHHOLDING":
            key = (component.line_id, component.code)
            actual[key] = actual.get(key, 0) + component.amount_doc
    if {k: v for k, v in expected.items() if v} != actual:
        raise ValueError("credit withholding does not reverse observed original treatment")
    if withholding.retention_doc != _ratio(guarantee_base, 500, 10000):
        raise ValueError("credit guarantee does not reverse observed original guarantee")


def build_ap_journal(*, company: str, vendor: str, currency: str, doc_id: str,
                     invoice_number: str, invoice_date: str, posting_date: str,
                     decision: PostingDecision, reconciliation_account: str,
                     valuation: ValuationResult, tax: TaxResult, withholding: WithholdingResult,
                     document_type: Literal["INVOICE", "CREDIT_NOTE"] = "INVOICE",
                     advances: Iterable[AdvanceApplication] = (), state: AdvanceState = AdvanceState(),
                     invoice_orders: tuple[str, ...] = (),
                     order_bindings: Iterable[InvoiceLineOrder] = (),
                     credit_references: Iterable[CreditReference] = (), rates: RateTable | None = None,
                     context: ValidationContext | None = None) -> APJournalResult:
    """Assemble and validate all monetary components; state remains caller-owned.

    Supplier rounding is the balanced residual, never a guessed FX plug.
    Non-monetary advance differences change the explicit cost/asset assignment;
    monetary differences use 668/768 only with explicit classification evidence.
    """
    balances, event = _scope(company=company, vendor=vendor, currency=currency, doc_id=doc_id,
                             invoice_number=invoice_number, invoice_date=invoice_date,
                             posting_date=posting_date, decision=decision, rates=rates, state=state)
    if reconciliation_account not in {"40000000", "41000000", "40300000"}:
        raise ValueError("explicit AP reconciliation account required")
    scope = APComponentScope(company, vendor, currency, doc_id, invoice_date, decision)
    for name, result in (("valuation", valuation), ("tax", tax), ("withholding", withholding)):
        if result.scope != scope:
            raise ValueError(f"{name} component scope differs from this invoice or is unresolved")
    if (valuation.status != "VALUED" or valuation.decision != decision
            or (valuation.company, valuation.currency) != (company, currency)):
        raise ValueError("valuation is not eligible for this posting scope")
    if tax.net_doc != valuation.net_doc:
        raise ValueError("fiscal and net valuation bases differ")
    bases: dict[str, int] = {}
    for component in valuation.components:
        bases[component.line_id] = bases.get(component.line_id, 0) + component.amount_doc
    fiscal_ids: set[str] = set()
    for component in tax.components:
        if component.line_id in fiscal_ids:
            raise ValueError("duplicate fiscal base id")
        fiscal_ids.add(component.line_id)
        if component.line_id not in bases:
            if component.base_doc == 0 and component.tax_code == "SIMP":
                continue
            raise ValueError("fiscal base is not resolved to a valued invoice line")
        if component.base_doc != bases[component.line_id]:
            raise ValueError("fiscal and valued amounts differ on an invoice line")
    if set(bases) - fiscal_ids:
        raise ValueError("valued invoice line lacks resolved fiscal treatment")
    bindings: dict[tuple[str, str], int] = {}
    assignment_map = dict(valuation.assignments)
    for binding in order_bindings:
        for value, name in ((binding.line_id, "bound invoice line"), (binding.po, "bound PO"),
                            (binding.reference, "line/PO binding evidence")):
            _text(value, name)
        key = (binding.line_id, binding.po)
        if key in bindings or binding.line_id not in assignment_map or binding.po not in invoice_orders:
            raise ValueError("invalid or duplicate invoice line/PO binding")
        base = nonnegative(binding.base_doc, "bound PO portion base")
        if not base:
            raise ValueError("positive bound PO portion base required")
        bindings[key] = base
    for line_id in assignment_map:
        if sum(amount for (lid, _), amount in bindings.items() if lid == line_id) > bases.get(line_id, 0):
            raise ValueError("bound PO portions exceed valued invoice line")
    if document_type not in {"INVOICE", "CREDIT_NOTE"}:
        raise ValueError("invoice or credit-note document type required")
    advances = tuple(advances)
    if document_type == "CREDIT_NOTE":
        if advances:
            raise ValueError("credit-note advance restoration requires separate resolved evidence")
        _credit_imputation(company=company, vendor=vendor, currency=currency,
                           invoice_date=invoice_date,
                           reconciliation_account=reconciliation_account, valuation=valuation,
                           tax=tax, withholding=withholding, references=credit_references)
    lines: list[JournalLine] = []
    tax_codes = {component.line_id: component.tax_code for component in tax.components}
    for component in valuation.components:
        lines.append(fiscal_line(component.account, abs(component.amount_doc), abs(component.amount_local),
                                 currency, tax_codes.get(component.line_id) if component.kind != "GR_IR" else None,
                                 credit=component.amount_local < 0, partner=component.partner,
                                 cost_center=component.cost_center, wbs=component.wbs,
                                 assignment=f"{component.order.po}/{component.order.item}" if component.order else None))
    for component in tax.components:
        for line in component.journal_lines:
            if line.get("currency") != currency:
                raise ValueError("tax component currency differs from invoice")
            if line["account"].startswith(("2", "6")):
                coding = assignment_map.get(component.line_id)
                if coding is None or (line["account"], line.get("cost_center"), line.get("wbs")) != (
                        coding.account, coding.cost_center, coding.wbs):
                    raise ValueError("non-deductible VAT differs from resolved line imputation")
            lines.append(dict(line))
    for component in withholding.components:
        line = component.journal_line
        if line.get("currency") != currency or line.get("partner") != vendor:
            raise ValueError("withholding component scope differs from invoice")
        if component.kind == "GUARANTEE" and line.get("assignment") != invoice_number:
            raise ValueError("guarantee invoice assignment differs from invoice")
        if component.kind == "GUARANTEE" and component.base_doc > valuation.net_doc:
            raise ValueError("guarantee base exceeds invoice net")
        if component.kind == "WITHHOLDING" and (
                component.line_id not in bases or component.base_doc > bases[component.line_id]):
            raise ValueError("withholding base is not resolved within the valued invoice line")
        lines.append(dict(line))
    advance_doc = 0
    usages: list[AdvanceUsage] = []
    seen: set[tuple[str, str | None]] = set()
    consumed_portions: dict[tuple[str, str], int] = {}
    for application in advances:
        application_key = (application.advance_id, application.line_id)
        if application_key in seen:
            raise ValueError("duplicate advance application")
        seen.add(application_key)
        balance = balances.get((company, application.advance_id))
        if balance is None or (balance.vendor, balance.currency) != (vendor, currency):
            raise ValueError("advance not found in invoice company/vendor/currency scope")
        if balance.po not in invoice_orders:
            raise ValueError("advance PO is not explicitly resolved to this invoice")
        if balance.original_date > invoice_date:
            raise ValueError("advance originates after invoice")
        amount = nonnegative(application.amount_doc, "advance application")
        if not amount or amount > balance.amount_doc - balance.used_doc:
            raise ValueError("advance application must be positive and within remaining balance")
        portion = (application.line_id, balance.po)
        if application.line_id is None or portion not in bindings:
            raise ValueError("advance requires resolved invoice line/PO portion")
        consumed_portions[portion] = consumed_portions.get(portion, 0) + amount
        if consumed_portions[portion] > bindings[portion]:
            raise ValueError("advance applications exceed the linked invoiced PO portion")
        if application.treatment not in {"NON_MONETARY", "MONETARY"}:
            raise ValueError("unknown advance classification: explicit evidence required")
        _text(application.treatment_reference, "advance classification evidence")
        # Cumulative original carrying amount guarantees exact exhaustion. The
        # final application consumes the booked residual including rounding cents.
        new_doc = balance.used_doc + amount
        new_local = _ratio(balance.amount_local, new_doc, balance.amount_doc)
        historical = new_local - balance.used_local
        if not historical:
            raise ValueError("positive advance application has no representable historical carrying amount")
        current = local_amount(amount, company, currency, invoice_date, rates)
        delta = historical - current
        if application.treatment == "NON_MONETARY":
            coding = application.cost_assignment
            if coding is None or coding.company != company:
                raise ValueError("non-monetary advance requires explicit expense/asset imputation")
            if (application.line_id is None or assignment_map.get(application.line_id) != coding
                    or (application.line_id, balance.po) not in bindings):
                raise ValueError("non-monetary advance imputation lacks resolved invoice line/PO binding")
            if (not isinstance(coding.account, str) or len(coding.account) != 8
                    or not coding.account.isdigit() or not coding.account.startswith(("2", "6"))
                    or bool(coding.cost_center) == bool(coding.wbs)):
                raise ValueError("non-monetary advance requires expense/asset account")
            for value in (coding.cost_center, coding.wbs):
                if value is not None and (not isinstance(value, str) or not value):
                    raise ValueError("invalid non-monetary advance cost object")
            if delta:
                lines.append(fiscal_line(coding.account, abs(delta), abs(delta), company_local_currency(company),
                                         None, credit=delta < 0, cost_center=coding.cost_center, wbs=coding.wbs))
        else:
            if application.cost_assignment is not None:
                raise ValueError("monetary FX settlement must not change expense/asset coding")
            if delta:
                lines.append(fiscal_line("66800000" if delta > 0 else "76800000", abs(delta), abs(delta),
                                         company_local_currency(company), None, credit=delta < 0))
        lines.append(fiscal_line("40700000", amount, historical, currency, None,
                                 credit=True, partner=vendor, assignment=balance.invoice_number))
        balances[(company, application.advance_id)] = replace(balance, used_doc=new_doc, used_local=new_local)
        usages.append(AdvanceUsage(balance.advance_id, amount, historical, current,
                                   application.treatment, application.treatment_reference))
        advance_doc += amount
    payable_doc = tax.gross_doc - withholding.deduction_doc - advance_doc
    payable_local = sum(line["debit"] - line["credit"] for line in lines)
    if advance_doc > valuation.net_doc or payable_doc < 0 or payable_local < 0:
        raise ValueError("deductions exceed invoice gross")
    lines.append(fiscal_line(reconciliation_account, payable_doc, payable_local, currency, None,
                             credit=True, partner=vendor, assignment=invoice_number))
    if document_type == "CREDIT_NOTE":
        lines = [{**line, "debit": line["credit"], "credit": line["debit"]} for line in lines]
    entry = _entry(company, currency, invoice_number, invoice_date, posting_date, lines, document_type, context)
    new_state = AdvanceState(tuple(balances[k] for k in sorted(balances)), (*state.events, event))
    return APJournalResult(document_type, payable_doc, payable_local, entry, new_state, tuple(usages))


def build_down_payment_request(*, company: str, vendor: str, vendor_country: str,
                               vendor_master: Mapping[str, Any],
                               currency: str, doc_id: str, invoice_number: str,
                               invoice_date: str, posting_date: str, amount_doc: int,
                               decision: PostingDecision, order: ApprovedAdvanceOrder,
                               rates: RateTable | None = None, state: AdvanceState = AdvanceState(),
                               context: ValidationContext | None = None) -> APJournalResult:
    balances, event = _scope(company=company, vendor=vendor, currency=currency, doc_id=doc_id,
                             invoice_number=invoice_number, invoice_date=invoice_date,
                             posting_date=posting_date, decision=decision, rates=rates, state=state)
    country = "MX" if company == "3100" else "PT" if company == "2100" else "ES"
    _text(vendor_country, "vendor country")
    if (not re.fullmatch("[A-Z]{2}", vendor_country) or vendor_country == "ZZ"
            or vendor_master.get("id") != vendor or vendor_master.get("country") != vendor_country
            or company not in vendor_master.get("companies", ())):
        raise ValueError("foreign vendor country requires matching ISO/master/company evidence")
    if vendor_country == country:
        raise ValueError("down-payment request policy requires a foreign vendor")
    if (order.company, order.vendor, order.currency) != (company, vendor, currency):
        raise ValueError("approved advance PO belongs to another scope")
    if order.approved is not True:
        raise ValueError("foreign advance requires explicitly approved PO")
    _text(order.po, "advance PO")
    _text(order.approval_reference, "PO approval evidence")
    if not nonnegative(amount_doc, "advance request amount") or (company, doc_id) in balances:
        raise ValueError("positive new advance request required")
    amount_local = local_amount(amount_doc, company, currency, invoice_date, rates)
    entry = _entry(company, currency, invoice_number, invoice_date, posting_date, [
        fiscal_line("40700000", amount_doc, amount_local, currency, None, partner=vendor, assignment=order.po),
        fiscal_line("40000000", amount_doc, amount_local, currency, None, credit=True,
                    partner=vendor, assignment=invoice_number)], "DOWN_PAYMENT_REQUEST", context)
    balances[(company, doc_id)] = AdvanceBalance(doc_id, company, vendor, currency, invoice_number,
                                                invoice_date, order.po, amount_doc, amount_local)
    new_state = AdvanceState(tuple(balances[k] for k in sorted(balances)), (*state.events, event))
    return APJournalResult("DOWN_PAYMENT_REQUEST", amount_doc, amount_local, entry, new_state)
