"""Evidence-driven HOLD gates and exact per-line price tolerance (#49)."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, DecimalException, localcontext

from .ap_allocation import AllocationResult, OrderKey
from .ap_rejections import (
    UNKNOWN, RuleCheck, bool_field, evaluate_ordered_checks, resolve_field,
)
from .facts import Evidence, Fact
from .money import RateTable, decimal, integer


HOLD_CODES = ("VENDOR_NOT_IN_MASTER", "BANK_DETAILS_CHANGED", "QTY_NOT_RECEIVED", "PRICE_VARIANCE")


@dataclass(frozen=True)
class HoldScope:
    company: str
    vendor: str
    currency: str
    invoice_id: str

    def __post_init__(self):
        if any(not isinstance(v, str) or not v for v in
               (self.company, self.vendor, self.currency, self.invoice_id)):
            raise ValueError("explicit company/vendor/currency/invoice scope required")


@dataclass(frozen=True)
class PricePortion:
    order: OrderKey
    quantity_milli: int
    po_unit_price_cents: tuple[Fact, ...]


@dataclass(frozen=True)
class PriceLine:
    line_id: str
    invoice_unit_price_cents: tuple[Fact, ...]
    portions: tuple[PricePortion, ...]


def _or(*values):
    return True if True in values else None if None in values else False


def _and(*values):
    return False if False in values else None if None in values else True


def _not(value):
    return None if value is None else not value


def bank_safety_check(fields):
    values, evidence, diagnostics = {}, [], []
    for name in ("bank_differs", "signed_change_supported", "factoring_supported", "similar_domain"):
        value, proof, notes = bool_field(fields, name)
        values[name] = value
        evidence.extend(proof)
        diagnostics.extend(notes)
    # The support predicates include the invoice IBAN, scope and chronological
    # validity. Active factoring alone never permits an arbitrary bank account.
    violation = _or(values["similar_domain"], _and(values["bank_differs"],
                    _not(_or(values["signed_change_supported"], values["factoring_supported"]))))
    return RuleCheck(HOLD_CODES[1], violation, tuple(evidence), tuple(diagnostics))


def receipt_quantity_check(scope: HoldScope, allocation: AllocationResult | None, *,
                           evidence: tuple[Evidence, ...], catalog_complete: Fact | None):
    """Use #44's atomic allocation; never publish its provisional consumption."""
    if allocation is None:
        return RuleCheck(HOLD_CODES[2], None, evidence, ("MISSING_ALLOCATION",))
    if (allocation.company, allocation.vendor, allocation.currency, allocation.invoice_id) != (
            scope.company, scope.vendor, scope.currency, scope.invoice_id):
        raise ValueError("allocation scope differs from invoice")
    if allocation.status == "ALLOCATED":
        return RuleCheck(HOLD_CODES[2], False, evidence)
    if allocation.status != "BLOCKED":
        raise ValueError("unsupported allocation status")
    complete = None if catalog_complete is None else catalog_complete.value
    if complete is not None and type(complete) is not bool:
        raise TypeError("catalog completeness must be boolean")
    proof = evidence + (() if catalog_complete is None else (catalog_complete.evidence,))
    codes = {d.code for d in allocation.diagnostics}
    # An unresolved reference/unit/replay/scope problem is not a receipt shortage.
    if complete is True and codes and codes <= {"INSUFFICIENT_RECEIPTS"}:
        return RuleCheck(HOLD_CODES[2], True, proof)
    return RuleCheck(HOLD_CODES[2], None, proof, tuple(sorted(codes)) or ("UNKNOWN_ALLOCATION",))


def price_variance_check(scope: HoldScope, invoice_date: Fact, lines: tuple[PriceLine, ...], *,
                         allocation: AllocationResult | None,
                         rates: RateTable | None = None, rate_evidence: tuple[Evidence, ...] = ()):
    """Strict unit-price >2% OR signed line increase >150 EUR, without rounding.

    For mixed-PO lines, test unit-price percentages against every PO portion and
    sum signed quantity-times-price differences once per original invoice line.
    Compare document cents to 15000 * units-per-EUR at the invoice date: no FX
    division/rounding can conceal a small but real threshold excess.
    """
    if not isinstance(invoice_date, Fact):
        raise TypeError("invoice date requires Fact")
    evidence, diagnostics = [invoice_date.evidence], []
    try:
        day = date.fromisoformat(invoice_date.value)
        if day.isoformat() != invoice_date.value:
            raise ValueError("canonical invoice date required")
    except (TypeError, ValueError):
        return RuleCheck(HOLD_CODES[3], None, tuple(evidence), ("INVALID_INVOICE_DATE",))
    if not lines:
        return RuleCheck(HOLD_CODES[3], None, tuple(evidence), ("MISSING_PRICE_LINES",))
    if len({line.line_id for line in lines}) != len(lines):
        raise ValueError("duplicate price line")
    if allocation is None or allocation.status != "ALLOCATED":
        return RuleCheck(HOLD_CODES[3], None, tuple(evidence), ("UNAVAILABLE_ALLOCATION",))
    if (allocation.company, allocation.vendor, allocation.currency, allocation.invoice_id) != (
            scope.company, scope.vendor, scope.currency, scope.invoice_id):
        raise ValueError("allocation scope differs from price invoice")
    allocated, priced = {}, {}
    for part in allocation.allocations:
        key = (part.line_id, part.order)
        allocated[key] = allocated.get(key, 0) + part.quantity_milli
    for line in lines:
        for part in line.portions:
            key = (line.line_id, part.order)
            priced[key] = priced.get(key, 0) + integer(part.quantity_milli, "price quantity")
    if allocated != priced:
        raise ValueError("price quantities must cover exactly the #44 allocations")
    proven, unknown = False, False
    with localcontext() as ctx:
        ctx.prec = 50
        for line in lines:
            if not isinstance(line.line_id, str) or not line.line_id:
                raise ValueError("price line requires identifier")
            invoice, proof, notes = resolve_field({"price": line.invoice_unit_price_cents}, "price")
            evidence.extend(proof)
            if invoice is UNKNOWN or not line.portions:
                unknown = True
                diagnostics.extend(notes or (f"MISSING_PRICE_PORTIONS:{line.line_id}",))
                continue
            try:
                invoice = decimal(invoice)
                if invoice < 0:
                    raise ValueError("negative invoice unit price")
            except (TypeError, ValueError, DecimalException):
                unknown = True
                diagnostics.append(f"INVALID_INVOICE_PRICE:{line.line_id}")
                continue
            delta, line_unknown, percent_excess = Decimal(0), False, False
            for portion in line.portions:
                if (portion.order.company, portion.order.vendor, portion.order.currency) != (
                        scope.company, scope.vendor, scope.currency):
                    raise ValueError("price portion scope differs from invoice")
                if integer(portion.quantity_milli, "price quantity") <= 0:
                    raise ValueError("price quantity must be positive")
                po, proof, notes = resolve_field({"price": portion.po_unit_price_cents}, "price")
                evidence.extend(proof)
                if po is UNKNOWN:
                    line_unknown = True
                    diagnostics.extend(notes)
                    continue
                try:
                    po = decimal(po)
                    if po < 0:
                        raise ValueError("negative PO unit price")
                except (TypeError, ValueError, DecimalException):
                    line_unknown = True
                    diagnostics.append(f"INVALID_PO_PRICE:{line.line_id}")
                    continue
                percent_excess = percent_excess or invoice * 100 > po * 102
                delta += (invoice - po) * Decimal(portion.quantity_milli) / 1000
            if percent_excess:
                proven = True
                continue
            if line_unknown:
                unknown = True
                continue
            if delta <= 0:
                continue
            if scope.currency == "EUR":
                rate = Decimal(1)
            elif rates is None or not rate_evidence:
                unknown = True
                diagnostics.append("MISSING_EUR_RATE_EVIDENCE")
                continue
            else:
                try:
                    rate = rates.as_of(day, scope.currency)
                    evidence.extend(rate_evidence)
                except ValueError:
                    unknown = True
                    diagnostics.append("MISSING_INVOICE_DATE_EUR_RATE")
                    continue
            proven = proven or delta > Decimal(15000) * rate
    return RuleCheck(HOLD_CODES[3], True if proven else None if unknown else False,
                     tuple(evidence), tuple(diagnostics))


def _optional_check(fields, applicable_name, supplied, code):
    applies, evidence, diagnostics = bool_field(fields, applicable_name)
    if applies is None:
        return RuleCheck(code, None, evidence, diagnostics)
    if not applies:
        return RuleCheck(code, False, evidence)
    if supplied is None:
        return RuleCheck(code, None, evidence, ("MISSING_CHECK",))
    if supplied.code != code:
        raise ValueError("unexpected supplied rule")
    return RuleCheck(code, supplied.violation, evidence + supplied.evidence, supplied.diagnostics)


def evaluate_holds(fields, *, quantity_check=None, price_check=None):
    """Run only after duplicate and rejection gates are known clear."""
    in_master, evidence, diagnostics = bool_field(fields, "vendor_in_master")
    checks = (
        RuleCheck(HOLD_CODES[0], _not(in_master), evidence, diagnostics),
        bank_safety_check(fields),
        _optional_check(fields, "quantity_check_applicable", quantity_check, HOLD_CODES[2]),
        _optional_check(fields, "price_check_applicable", price_check, HOLD_CODES[3]),
    )
    return evaluate_ordered_checks(checks, HOLD_CODES, "HOLD")
