"""Typed in-memory results of the AR billing workflow (policies §3.1).

One ``BillingResult`` per billing item. Amounts are integer cents in the company's local
currency; dates are ``YYYY-MM-DD``. Delivery rows (``output_models.ArBillingRow``) are
produced from these instances by ``to_row``; nothing here reads files.
"""
from dataclasses import dataclass, field
from enum import StrEnum

from ..model import Cents, CompanyCode, Diagnostic, IsoDate, JournalEntry, Month
from ..facts import Evidence


class BillingType(StrEnum):
    OBRA_CERTIFICATION = "OBRA_CERTIFICATION"
    SERVICE_MONTHLY = "SERVICE_MONTHLY"
    PRICE_REVISION = "PRICE_REVISION"
    PPA = "PPA"
    MARKET_SETTLEMENT = "MARKET_SETTLEMENT"


class Decision(StrEnum):
    INVOICE = "INVOICE"
    SKIP_PENDING_APPROVAL = "SKIP_PENDING_APPROVAL"


@dataclass(frozen=True, slots=True)
class BillingItem:
    """One entry of ``tasks/ar_billing_items.json`` with its ``item.json`` metadata."""

    id: str
    type: BillingType
    company: CompanyCode
    contract: str
    customer: str
    month: Month
    """Invoice month for services, revisions, PPA and market; certified month for works."""


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    """Income line. ``amount`` may be negative (market deviations). Exactly one cost object."""

    description: str
    amount: Cents
    account: str
    wbs: str | None = None
    cost_center: str | None = None

    def __post_init__(self) -> None:
        if (self.wbs is None) == (self.cost_center is None):
            raise ValueError("an invoice line needs exactly one of wbs and cost_center")


@dataclass(frozen=True, slots=True)
class Deduction:
    code: str
    """``MX5MILL`` (inspection levy) or ``ADV_AMORT`` (advance amortization)."""
    amount: Cents
    account: str


@dataclass(frozen=True, slots=True)
class Face:
    oficina_contable: str
    organo_gestor: str
    unidad_tramitadora: str


@dataclass(frozen=True, slots=True)
class Invoice:
    number: str
    date: IsoDate
    due_date: IsoDate
    tax_code: str
    net: Cents
    tax: Cents
    gross: Cents
    retention: Cents
    deductions: tuple[Deduction, ...]
    payable: Cents
    currency: str
    lines: tuple[InvoiceLine, ...]
    face: Face | None = None

    def __post_init__(self) -> None:
        if sum(line.amount for line in self.lines) != self.net:
            raise ValueError("invoice lines must add up to net")
        if self.gross != self.net + self.tax:
            raise ValueError("gross must equal net + tax")
        if self.payable != self.gross - self.retention - sum(d.amount for d in self.deductions):
            raise ValueError("payable must equal gross - retention - deductions")


@dataclass(frozen=True, slots=True)
class BillingResult:
    """Outcome for one item. ``invoice`` and ``journal_entry`` exist iff ``decision`` is INVOICE."""

    item: BillingItem
    decision: Decision
    invoice: Invoice | None = None
    journal_entry: JournalEntry | None = None
    evidence: tuple[Evidence, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    """Non-blocking notes (omitted pending extras, cross-check warnings)."""

    def __post_init__(self) -> None:
        invoiced = self.decision is Decision.INVOICE
        if invoiced != (self.invoice is not None) or invoiced != (self.journal_entry is not None):
            raise ValueError("invoice and journal entry exist exactly when the decision is INVOICE")


@dataclass(frozen=True, slots=True)
class Unresolved:
    """An item the engine refused to decide: no record is emitted, only the reasons."""

    item: BillingItem
    reasons: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class BillingRun:
    results: tuple[BillingResult, ...]
    """In input order, resolved items only."""
    unresolved: tuple[Unresolved, ...] = field(default=())
