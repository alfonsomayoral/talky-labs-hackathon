"""Atomic in-memory AP posting from resolved, evidenced inputs (#140).

Every factory result is tentative until the real AP output validator accepts the
row. This module performs no extraction, policy decisions, file writes or I/O.
"""
from dataclasses import dataclass, field
from datetime import date
import json

from .ap_allocation import (
    AllocationDiagnostic, ConsumptionState, InvoiceQuantityLine, OrderLine,
    Receipt, allocate_receipts,
)
from .ap_journal import (
    AdvanceApplication, AdvanceState, ApprovedAdvanceOrder, CreditReference, InvoiceLineOrder,
    build_ap_journal, build_down_payment_request,
)
from .ap_output import APHeader, POSTING, build_ap_row
from .ap_tax import TaxCatalog, TaxLine, calculate_ap_tax
from .ap_valuation import OrderPrice, ValuationLine, value_ap_lines
from .ap_withholding import (
    ContractGuarantee, WithholdingBase, WithholdingCatalog,
    calculate_ap_withholdings,
)
from .facts import Evidence
from .model.ap_component_scope import APComponentScope
from .model.validation_context import ValidationContext
from .money import RateTable, integer
from .output_models.ap import ApLine, ApPayee, ApRow


@dataclass(frozen=True)
class CodedAPLine:
    """An output portion explicitly linked to its valued/fiscal invoice line."""

    line_id: str
    line: ApLine


@dataclass(frozen=True, kw_only=True)
class APPostingInputs:
    header: APHeader
    country: str
    posting_date: str
    reconciliation_account: str
    gr_ir_account: str
    valuation_lines: tuple[ValuationLine, ...]
    tax_lines: tuple[TaxLine, ...]
    withholding_bases: tuple[WithholdingBase, ...]
    coded_lines: tuple[CodedAPLine, ...]
    quantity_lines: tuple[InvoiceQuantityLine, ...] = ()
    order_catalog: tuple[OrderLine, ...] = ()
    receipt_catalog: tuple[Receipt, ...] = ()
    order_prices: tuple[OrderPrice, ...] = ()
    receipt_as_of: str | None = None
    guarantee: ContractGuarantee | None = None
    advances: tuple[AdvanceApplication, ...] = ()
    invoice_orders: tuple[str, ...] = ()
    order_bindings: tuple[InvoiceLineOrder, ...] = ()
    credit_references: tuple[CreditReference, ...] = ()
    payee: ApPayee | None = None
    payment_block: str | None = None


@dataclass(frozen=True, kw_only=True)
class APDownPaymentInputs:
    header: APHeader
    posting_date: str
    order: ApprovedAdvanceOrder
    vendor_master: dict
    po_item: int
    tax_code: str


@dataclass(frozen=True, kw_only=True)
class APTransactionRequest:
    scope: APComponentScope
    document_type: str
    evidence: tuple[Evidence, ...]
    posting: APPostingInputs | APDownPaymentInputs | None = None


@dataclass(frozen=True)
class _Publication:
    key: tuple[str, str, str, str]
    row_json: str
    evidence: tuple[Evidence, ...]


@dataclass(frozen=True)
class APTransactionState:
    """Caller-owned snapshot; published rows cannot expose mutable ledger data.

    The constructor accepts historical consumption/advance baselines. New
    publications are created only by ``commit_ap_transaction`` after validation.
    """

    consumption: ConsumptionState = ConsumptionState()
    advances: AdvanceState = AdvanceState()
    _published: tuple[_Publication, ...] = field(default=(), init=False, repr=False)

    def __post_init__(self):
        if not isinstance(self.consumption, ConsumptionState) or not isinstance(self.advances, AdvanceState):
            raise TypeError("transaction state requires receipt and advance snapshots")
        if any(not isinstance(items, tuple) for items in (
                self.consumption.usages, self.consumption.invoices,
                self.advances.balances, self.advances.events)):
            raise TypeError("transaction state requires immutable tuple snapshots")
        if any(not isinstance(key, tuple) for key in (
                *self.consumption.invoices, *self.advances.events)):
            raise TypeError("historical event keys must be immutable tuples")
        if any(len(key) != 4 or any(not isinstance(value, str) or not value for value in key)
               for key in (*self.consumption.invoices, *self.advances.events)):
            raise ValueError("historical event requires company/vendor/currency/document identity")

    @property
    def keys(self) -> tuple[tuple[str, str, str, str], ...]:
        return tuple(publication.key for publication in self._published)

    @property
    def rows(self) -> tuple[ApRow, ...]:
        """Fresh delivery objects; mutating a returned row never mutates state."""
        return tuple(json.loads(publication.row_json) for publication in self._published)

    @property
    def evidence(self) -> tuple[tuple[Evidence, ...], ...]:
        return tuple(publication.evidence for publication in self._published)


@dataclass(frozen=True)
class APTransactionResult:
    status: str  # COMMITTED, BLOCKED, NOT_POSTING
    state: APTransactionState
    diagnostics: tuple[AllocationDiagnostic, ...] = ()

    @property
    def row(self) -> ApRow | None:
        return self.state.rows[-1] if self.status == "COMMITTED" else None


def _iso(value: str, name: str) -> None:
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError(f"explicit ISO {name} required")


def _coded_projection(inputs: APPostingInputs) -> tuple[ApLine, ...]:
    """Keep the coded output tied to the very inputs sent to the real factories."""
    valued = {line.line_id: line for line in inputs.valuation_lines}
    fiscal = {line.line_id: line for line in inputs.tax_lines}
    if len(valued) != len(inputs.valuation_lines) or len(fiscal) != len(inputs.tax_lines):
        raise ValueError("unique valued and fiscal line identities required")
    amounts = {line_id: 0 for line_id in valued}
    rows = []
    for coded in inputs.coded_lines:
        if not isinstance(coded, CodedAPLine) or coded.line_id not in valued or coded.line_id not in fiscal:
            raise ValueError("coded output must identify its valued and fiscal line")
        row, assignment = coded.line, valued[coded.line_id].assignment
        if not isinstance(row, dict):
            raise TypeError("coded output must be an AP line object")
        if (row.get("account"), row.get("cost_center"), row.get("wbs")) != (
                assignment.account, assignment.cost_center, assignment.wbs):
            raise ValueError("coded output differs from resolved cost imputation")
        if row.get("tax_code") != fiscal[coded.line_id].tax_code:
            raise ValueError("coded output differs from resolved fiscal treatment")
        amount = integer(row.get("amount"), "coded amount")
        if amount < 0:
            raise ValueError("unsigned coded document cents required")
        amounts[coded.line_id] += amount
        rows.append(row)
    if any(amounts[line_id] != line.amount_doc for line_id, line in valued.items()):
        raise ValueError("coded portions must conserve each valued invoice line")
    return tuple(rows)


def _allocated_coding(inputs: APPostingInputs, allocation) -> None:
    """Every coded PO portion belongs to this same allocated invoice line."""
    expected = {}
    for part in allocation.allocations:
        expected.setdefault(part.line_id, set()).add((part.order.po, part.order.item))
    actual = {line_id: set() for line_id in expected}
    for coded in inputs.coded_lines:
        if coded.line_id not in expected:
            continue
        position = (coded.line.get("po"), coded.line.get("po_item"))
        if position not in expected[coded.line_id]:
            raise ValueError("coded PO belongs to another allocated invoice line")
        actual[coded.line_id].add(position)
    if actual != expected:
        raise ValueError("coded PO portions do not cover the allocated invoice line positions")


def _publish(request, state, consumption, advance_state, row):
    scope = request.scope
    key = (scope.company, scope.vendor, scope.currency, scope.invoice_id)
    publication = _Publication(
        key, json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False), request.evidence,
    )
    committed = APTransactionState(consumption, advance_state)
    object.__setattr__(committed, "_published", (*state._published, publication))
    return APTransactionResult("COMMITTED", committed)


def _down_payment(request, state, inputs, tax_catalog, rates, context):
    scope = request.scope
    if not isinstance(inputs, APDownPaymentInputs) or not isinstance(inputs.order, ApprovedAdvanceOrder):
        raise TypeError("foreign down payment requires resolved approval/order/master inputs")
    if scope.decision != "POST":
        raise ValueError("approved foreign down payment requires POST")
    if integer(inputs.po_item, "advance PO position") <= 0:
        raise ValueError("explicit positive advance PO position required")
    country = "MX" if scope.company == "3100" else "PT" if scope.company == "2100" else "ES"
    treatment = tax_catalog.get(inputs.tax_code, country)
    if treatment.kind != "exempt" or treatment.rate != 0:
        raise ValueError("advance request requires evidenced zero-rate exempt treatment")
    if not isinstance(inputs.vendor_master, dict) or not isinstance(inputs.vendor_master.get("country"), str):
        raise ValueError("advance request requires the observed vendor country master")
    journal = build_down_payment_request(
        company=scope.company, vendor=scope.vendor,
        vendor_country=inputs.vendor_master["country"], vendor_master=inputs.vendor_master,
        currency=scope.currency, doc_id=scope.invoice_id,
        invoice_number=inputs.header.invoice_number, invoice_date=scope.invoice_date,
        posting_date=inputs.posting_date, amount_doc=inputs.header.net,
        decision=scope.decision, order=inputs.order, rates=rates,
        state=state.advances, context=context,
    )
    row = build_ap_row(
        doc_id=scope.invoice_id, document_type=request.document_type, decision=scope.decision,
        header=inputs.header, lines=[dict(amount=inputs.header.net, account="40700000",
                                         tax_code=inputs.tax_code, po=inputs.order.po, po_item=inputs.po_item)],
        journal_entry=journal.journal_entry, context=context, tax_catalog=tax_catalog,
    )
    return _publish(request, state, state.consumption, journal.state, row)


def commit_ap_transaction(
    request: APTransactionRequest, state: APTransactionState = APTransactionState(), *,
    tax_catalog: TaxCatalog | None = None,
    withholding_catalog: WithholdingCatalog | None = None,
    rates: RateTable | None = None, context: ValidationContext | None = None,
) -> APTransactionResult:
    """Return one new snapshot only after journal and AP-row validation succeed.

    Receipt catalogs are complete (including receipts consumed historically).
    Every quantity portion must carry explicit eligible receipt IDs; visibility
    uses an explicit observed cutoff, never a default derived from the invoice.
    A repeated committed key or published task ID raises before any factory runs.
    """
    if not isinstance(request, APTransactionRequest) or not isinstance(state, APTransactionState):
        raise TypeError("typed transaction request and state required")
    scope = request.scope
    if not isinstance(scope, APComponentScope):
        raise TypeError("transaction requires an explicit AP component scope")
    if (not isinstance(scope.invoice_id, str) or not scope.invoice_id
            or not isinstance(request.evidence, tuple) or not request.evidence
            or any(not isinstance(item, Evidence) for item in request.evidence)):
        raise ValueError("task identity and structured source evidence required")
    if scope.decision not in POSTING:
        if scope.decision not in {"HOLD", "REJECT", "DUPLICATE", "NOT_INVOICE"}:
            raise ValueError("resolved AP decision required; UNKNOWN cannot post")
        return APTransactionResult("NOT_POSTING", state)
    for value in (scope.company, scope.vendor, scope.currency):
        if not isinstance(value, str) or not value:
            raise ValueError("complete posting company/vendor/currency scope required")
    _iso(scope.invoice_date, "invoice date")
    key = (scope.company, scope.vendor, scope.currency, scope.invoice_id)
    historical_keys = (*state.consumption.invoices, *state.advances.events)
    if (key in state.keys or any((old[0], old[3]) == (scope.company, scope.invoice_id)
                               for old in historical_keys)
            or any(publication.key[3] == scope.invoice_id for publication in state._published)):
        raise ValueError("AP transaction key or task ID already committed")
    inputs = request.posting
    if not isinstance(inputs, (APPostingInputs, APDownPaymentInputs)) or not isinstance(inputs.header, APHeader):
        raise TypeError("posting requires typed resolved monetary inputs and header")
    if (inputs.header.company, inputs.header.vendor_id, inputs.header.currency,
            inputs.header.invoice_date) != (scope.company, scope.vendor, scope.currency, scope.invoice_date):
        raise ValueError("AP header differs from resolved posting scope")
    _iso(inputs.posting_date, "posting date")
    if not isinstance(tax_catalog, TaxCatalog):
        raise TypeError("active tax catalogue required")
    if request.document_type == "DOWN_PAYMENT_REQUEST":
        return _down_payment(request, state, inputs, tax_catalog, rates, context)
    if request.document_type not in {"INVOICE", "CREDIT_NOTE"} or not isinstance(inputs, APPostingInputs):
        raise ValueError("invoice transaction requires ordinary or resolved credit-note inputs")
    if request.document_type == "CREDIT_NOTE" and inputs.quantity_lines:
        raise ValueError("credit notes cannot consume new receipts; original imputation is required")
    if not isinstance(withholding_catalog, WithholdingCatalog):
        raise TypeError("active tax and withholding catalogues required")
    coded_lines = _coded_projection(inputs)
    allocation = None
    consumption = state.consumption
    if inputs.quantity_lines:
        _iso(inputs.receipt_as_of, "receipt visibility cutoff")
        receipts = {receipt.key: receipt for receipt in inputs.receipt_catalog}
        for line in inputs.quantity_lines:
            for portion in line.portions:
                if portion.receipt_ids is None:
                    raise ValueError("quantity portions require explicit eligible receipt IDs")
                for receipt_id in portion.receipt_ids:
                    receipt = receipts.get((scope.company, receipt_id))
                    if receipt is not None and receipt.posting_date > inputs.receipt_as_of:
                        raise ValueError("eligible receipt is after the explicit visibility cutoff")
        allocation = allocate_receipts(
            company=scope.company, vendor=scope.vendor, currency=scope.currency,
            invoice_id=scope.invoice_id, lines=inputs.quantity_lines,
            orders=inputs.order_catalog, receipts=inputs.receipt_catalog,
            state=state.consumption,
        )
        if allocation.status != "ALLOCATED":
            return APTransactionResult("BLOCKED", state, allocation.diagnostics)
        _allocated_coding(inputs, allocation)
        consumption = allocation.state
    valuation = value_ap_lines(
        company=scope.company, vendor=scope.vendor, currency=scope.currency,
        invoice_id=scope.invoice_id, invoice_date=scope.invoice_date, decision=scope.decision,
        lines=inputs.valuation_lines, gr_ir_account=inputs.gr_ir_account,
        prices=inputs.order_prices, allocation=allocation, rates=rates,
    )
    tax = calculate_ap_tax(
        company=scope.company, country=inputs.country, vendor=scope.vendor,
        currency=scope.currency, invoice_id=scope.invoice_id, invoice_date=scope.invoice_date,
        decision=scope.decision, lines=inputs.tax_lines, catalog=tax_catalog, rates=rates,
    )
    withholding = calculate_ap_withholdings(
        company=scope.company, country=inputs.country, vendor=scope.vendor,
        currency=scope.currency, invoice_id=scope.invoice_id, invoice_date=scope.invoice_date,
        invoice_number=inputs.header.invoice_number, decision=scope.decision,
        bases=inputs.withholding_bases, catalog=withholding_catalog,
        guarantee=inputs.guarantee, rates=rates,
    )
    journal = build_ap_journal(
        company=scope.company, vendor=scope.vendor, currency=scope.currency,
        doc_id=scope.invoice_id, invoice_number=inputs.header.invoice_number,
        invoice_date=scope.invoice_date, posting_date=inputs.posting_date, decision=scope.decision,
        reconciliation_account=inputs.reconciliation_account,
        valuation=valuation, tax=tax, withholding=withholding,
        document_type=request.document_type, advances=inputs.advances, state=state.advances,
        invoice_orders=inputs.invoice_orders, order_bindings=inputs.order_bindings,
        credit_references=inputs.credit_references, rates=rates, context=context,
    )
    row = build_ap_row(
        doc_id=scope.invoice_id, document_type=request.document_type, decision=scope.decision,
        header=inputs.header, lines=coded_lines, journal_entry=journal.journal_entry,
        payee=inputs.payee, payment_block=inputs.payment_block,
        context=context, tax_catalog=tax_catalog,
    )
    return _publish(request, state, consumption, journal.state, row)
