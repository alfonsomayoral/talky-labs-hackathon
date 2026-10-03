"""Net AP posting components from explicit eligibility, allocation and coding.

Policy §§1 and 2.3. Taxes, withholding, advances and the final supplier line
remain with their owning rules. No AP eligibility/tolerance decision is made.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re

from .ap_allocation import AllocationResult, OrderKey
from .money import company_local_currency, decimal, integer, line_amount


@dataclass(frozen=True)
class CostAssignment:
    company: str
    account: str
    cost_center: str | None = None
    wbs: str | None = None


@dataclass(frozen=True)
class ValuationLine:
    line_id: str
    amount_doc: int
    assignment: CostAssignment
    quantity_milli: int | None = None  # None means direct expense/asset without PO


@dataclass(frozen=True)
class OrderPrice:
    order: OrderKey
    unit_price_cents: Decimal | int | str


@dataclass(frozen=True)
class NetPostingComponent:
    line_id: str
    kind: str  # GR_IR, PRICE_DIFFERENCE, DIRECT
    account: str
    amount_doc: int  # signed debit; negative is a credit
    amount_local: int
    partner: str | None = None
    cost_center: str | None = None
    wbs: str | None = None
    order: OrderKey | None = None


@dataclass(frozen=True)
class ValuationResult:
    status: str
    decision: str
    company: str
    currency: str
    local_currency: str
    components: tuple[NetPostingComponent, ...] = ()
    net_doc: int = 0
    net_local: int = 0


def value_ap_lines(*, company, vendor, currency, invoice_id, invoice_date,
                   decision, lines, gr_ir_account, prices=(),
                   allocation: AllocationResult | None = None, rates=None):
    """Return net posting components, without constructing a delivery contract.

    A supplied POST/POST_PAYMENT_BLOCK decision authorizes calculation; other AP
    decisions return INELIGIBLE. Allocation failure returns UNALLOCATED. Every
    matched line must conserve its explicitly supplied quantity. The caller owns
    master validation and commits allocation state only after complete posting.
    """
    for value in (vendor, currency, invoice_id):
        if not isinstance(value, str) or not value:
            raise ValueError("nonempty scope reference required")
    local = company_local_currency(company)
    if date.fromisoformat(invoice_date).isoformat() != invoice_date:
        raise ValueError("invalid invoice date")
    if decision not in {"POST", "POST_PAYMENT_BLOCK", "HOLD", "REJECT", "DUPLICATE", "NOT_INVOICE"}:
        raise ValueError("explicit AP decision required")
    if decision not in {"POST", "POST_PAYMENT_BLOCK"}:
        return ValuationResult("INELIGIBLE", decision, company, currency, local)
    if not re.fullmatch(r"\d{8}", gr_ir_account):
        raise ValueError("invalid explicit GR/IR account")
    if currency != local and rates is None:
        raise ValueError("FX rates required for foreign currency")
    lines = tuple(lines)
    if not lines:
        raise ValueError("invoice requires valuation lines")
    line_map = {}
    for line in lines:
        if not isinstance(line.line_id, str) or not line.line_id or line.line_id in line_map:
            raise ValueError("unique nonempty invoice line required")
        if integer(line.amount_doc, "amount_doc") < 0:
            raise ValueError("credit notes require a separate reversal integration")
        if line.quantity_milli is not None and integer(line.quantity_milli, "quantity_milli") <= 0:
            raise ValueError("matched quantity must be positive")
        assignment = line.assignment
        if assignment.company != company:
            raise ValueError("cost assignment belongs to another company")
        if (not isinstance(assignment.account, str)
                or not re.fullmatch(r"[26]\d{7}", assignment.account)):
            raise ValueError("explicit expense or asset account required")
        if bool(assignment.cost_center) == bool(assignment.wbs):
            raise ValueError("exactly one cost center or WBS required")
        for value in (assignment.cost_center, assignment.wbs):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError("invalid cost object")
        line_map[line.line_id] = line
    matched = {l.line_id for l in lines if l.quantity_milli is not None}
    groups = {}
    if matched and (allocation is None or allocation.status != "ALLOCATED"):
        return ValuationResult("UNALLOCATED", decision, company, currency, local)
    if allocation is not None:
        if (allocation.company, allocation.vendor, allocation.currency, allocation.invoice_id) != (
                company, vendor, currency, invoice_id):
            raise ValueError("allocation belongs to another invoice scope")
        if allocation.status != "ALLOCATED":
            return ValuationResult("UNALLOCATED", decision, company, currency, local)
        for part in allocation.allocations:
            if part.line_id not in matched:
                raise ValueError("allocation contains unexpected/direct invoice line")
            if (part.order.company, part.order.vendor, part.order.currency) != (company, vendor, currency):
                raise ValueError("allocated order belongs to another scope")
            if integer(part.quantity_milli, "quantity_milli") <= 0:
                raise ValueError("allocated quantity must be positive")
            key = (part.line_id, part.order)
            groups[key] = groups.get(key, 0) + part.quantity_milli
    for line_id in matched:
        if sum(q for (lid, _), q in groups.items() if lid == line_id) != line_map[line_id].quantity_milli:
            raise ValueError("allocation does not conserve invoice line quantity")
    price_map = {}
    for price in prices:
        if price.order in price_map:
            raise ValueError("duplicate PO price")
        value = decimal(price.unit_price_cents)
        if value < 0:
            raise ValueError("PO price must be nonnegative")
        price_map[price.order] = value
    components = []

    def add(line, kind, account, amount, *, partner=None, order=None, cost=False):
        if not amount:
            return
        converted = amount if currency == local else rates.to_local(amount, currency, company, invoice_date)
        components.append(NetPostingComponent(
            line.line_id, kind, account, amount, converted, partner,
            line.assignment.cost_center if cost else None,
            line.assignment.wbs if cost else None, order,
        ))

    for line in lines:
        if line.line_id not in matched:
            add(line, "DIRECT", line.assignment.account, line.amount_doc, cost=True)
            continue
        received_value = 0
        for (line_id, order), quantity in sorted(groups.items()):
            if line_id != line.line_id:
                continue
            if order not in price_map:
                raise ValueError("explicit PO price missing")
            amount = line_amount(quantity, price_map[order])
            received_value += amount
            add(line, "GR_IR", gr_ir_account, amount, partner=vendor, order=order)
        add(line, "PRICE_DIFFERENCE", line.assignment.account,
            line.amount_doc - received_value, cost=True)
    return ValuationResult("VALUED", decision, company, currency, local, tuple(components),
                           sum(l.amount_doc for l in lines), sum(c.amount_local for c in components))
