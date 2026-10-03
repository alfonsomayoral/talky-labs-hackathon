"""AR tax, guarantees and Mexican deductions from explicit billing inputs.

Policy §§1 and 3.1 plus the phase tax-code master: no base calculation,
approval, document interpretation, FX, final journal or JSONL serialization.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, localcontext
import re

from .money import company_local_currency, integer, round_cents


# Stable challenge rules, confirmed against erp/tax_codes.json; rates in bp.
TAX_RATES = {"R21": 2100, "R10": 1000, "RISP": 0,
             "PR06": 600, "PR23": 2300, "PRAUT": 0, "MR16": 1600}


@dataclass(frozen=True)
class BillingScope:
    company: str
    currency: str
    contract: str
    customer: str


@dataclass(frozen=True)
class BillingBaseLine:
    scope: BillingScope
    line_id: str
    base_cents: int


@dataclass(frozen=True)
class BillingTerms:
    tax_code: str
    guarantee_bp: int
    mx_five_per_mille: bool
    advance_bp: int  # 0 or Mexican policy 3000; explicit, never inferred


@dataclass(frozen=True)
class AdvanceApplication:
    invoice_id: str
    invoice_date: str
    amount_cents: int


@dataclass(frozen=True)
class AdvanceState:
    scope: BillingScope
    available_cents: int  # AFTER the applications in history, not original advance
    history: tuple[AdvanceApplication, ...] = ()


@dataclass(frozen=True)
class TaxedBaseLine:
    line_id: str
    base_cents: int
    tax_cents: int


@dataclass(frozen=True)
class BillingDeduction:
    kind: str
    amount_cents: int
    debit_account: str
    partner: str | None


@dataclass(frozen=True)
class BillingAmounts:
    scope: BillingScope
    tax_code: str
    tax_legend: str | None
    lines: tuple[TaxedBaseLine, ...]
    base_cents: int
    tax_cents: int
    gross_cents: int
    guarantee_cents: int
    mx_levy_cents: int
    advance_cents: int
    payable_cents: int
    deductions: tuple[BillingDeduction, ...]
    advance_state: AdvanceState | None


def _nonnegative(value, name):
    if integer(value, name) < 0:
        raise ValueError(f"{name} must be nonnegative")


def _scope(scope):
    company_local_currency(scope.company)  # supported challenge company
    if not isinstance(scope.currency, str) or not re.fullmatch(r"[A-Z]{3}", scope.currency):
        raise ValueError("currency must be an ISO code")
    for value in (scope.contract, scope.customer):
        if not isinstance(value, str) or not value:
            raise ValueError("nonempty contract and customer required")


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError("date must be YYYY-MM-DD")


def _history(history):
    seen, previous = set(), ""
    for application in history:
        _day(application.invoice_date)
        if (not isinstance(application.invoice_id, str) or not application.invoice_id
                or application.invoice_id in seen):
            raise ValueError("unique historical invoice ID required")
        if application.invoice_date < previous:
            raise ValueError("advance history must be chronological")
        _nonnegative(application.amount_cents, "historical advance application")
        previous = application.invoice_date
        seen.add(application.invoice_id)


def advance_from_history(*, scope, received_cents, applications):
    """Build an explicit available balance without deducting history twice."""
    _scope(scope)
    _nonnegative(received_cents, "received advance")
    applications = tuple(sorted(applications, key=lambda a: (a.invoice_date, a.invoice_id)))
    _history(applications)
    available = received_cents - sum(a.amount_cents for a in applications)
    _nonnegative(available, "available advance")
    return AdvanceState(scope, available, applications)


def _percentage(amount, bp):
    with localcontext() as ctx:
        ctx.prec = 50
        return round_cents(Decimal(amount) * bp / 10000)


def calculate_billing_amounts(*, scope, invoice_id, invoice_date, lines, terms,
                              advance_state=None):
    """Calculate AR amounts from resolved billable base lines and contract terms.

    VAT rounds per base line; guarantee and Mexican levy each round on total net,
    and advance amortization rounds on total including VAT before the balance cap.
    Return a tentative new advance state, to be persisted only after full posting.
    """
    _scope(scope)
    _day(invoice_date)
    if not isinstance(invoice_id, str) or not invoice_id:
        raise ValueError("invoice ID required")
    if terms.tax_code not in TAX_RATES:
        raise ValueError("unsupported explicit billing tax code")
    if terms.tax_code.startswith("PR"):
        eligible_company = scope.company == "2100"
    elif terms.tax_code == "MR16":
        eligible_company = scope.company == "3100"
    else:
        eligible_company = scope.company not in {"2100", "3100"}
    if not eligible_company:
        raise ValueError("tax code does not belong to company's jurisdiction")
    if not 0 <= integer(terms.guarantee_bp, "guarantee_bp") <= 10000:
        raise ValueError("guarantee_bp must be between 0 and 10000")
    if type(terms.mx_five_per_mille) is not bool:
        raise TypeError("mx_five_per_mille must be explicit boolean")
    if integer(terms.advance_bp, "advance_bp") not in {0, 3000}:
        raise ValueError("advance rate must be zero or policy 30%")
    if (terms.mx_five_per_mille or terms.advance_bp) and terms.tax_code != "MR16":
        raise ValueError("Mexican deductions require MR16")
    if terms.advance_bp and advance_state is None:
        raise ValueError("explicit advance balance/history required")
    if advance_state is not None:
        if advance_state.scope != scope:
            raise ValueError("advance belongs to another company/currency/contract/customer")
        _nonnegative(advance_state.available_cents, "available advance")
        _history(advance_state.history)
        if any(a.invoice_id == invoice_id for a in advance_state.history):
            raise ValueError("invoice already present in advance history")
        if advance_state.history and invoice_date < advance_state.history[-1].invoice_date:
            raise ValueError("invoice precedes existing advance history")
    lines = tuple(lines)
    if not lines:
        raise ValueError("resolved base lines required")
    taxed, seen = [], set()
    for line in lines:
        if line.scope != scope:
            raise ValueError("base line belongs to another billing scope")
        if not isinstance(line.line_id, str) or not line.line_id or line.line_id in seen:
            raise ValueError("unique nonempty base line ID required")
        _nonnegative(line.base_cents, "base_cents")
        seen.add(line.line_id)
        taxed.append(TaxedBaseLine(line.line_id, line.base_cents,
                                   _percentage(line.base_cents, TAX_RATES[terms.tax_code])))
    base, tax = sum(l.base_cents for l in taxed), sum(l.tax_cents for l in taxed)
    gross = base + tax
    guarantee = _percentage(base, terms.guarantee_bp)
    levy = _percentage(base, 50) if terms.mx_five_per_mille else 0
    advance = min(_percentage(gross, terms.advance_bp), advance_state.available_cents) if terms.advance_bp else 0
    payable = gross - guarantee - levy - advance
    if payable < 0:
        raise ValueError("contract deductions exceed invoice gross")
    new_state = advance_state
    if terms.advance_bp:
        new_state = AdvanceState(scope, advance_state.available_cents - advance,
            (*advance_state.history, AdvanceApplication(invoice_id, invoice_date, advance)))
    deductions = tuple(BillingDeduction(kind, amount, account, partner)
                       for kind, amount, account, partner in (
                           ("GUARANTEE", guarantee, "43000900", scope.customer),
                           ("MX5MILL", levy, "63100000", None),
                           ("ADVANCE", advance, "43800000", scope.customer),
                       ) if amount)
    legend = "Inversión del sujeto pasivo: art. 84.Uno.2º f) LIVA" if terms.tax_code == "RISP" else None
    return BillingAmounts(scope, terms.tax_code, legend, tuple(taxed), base, tax, gross,
                          guarantee, levy, advance, payable, deductions, new_state)
