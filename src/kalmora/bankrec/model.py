"""Typed in-memory results of the bank reconciliation (policy §4).

One ``AccountReconciliation`` per bank account. Amounts are integer cents: statement
lines in the account's currency, adjustments in the company's functional currency.
Delivery rows (``output_models.BankRecRow``) are produced by ``rows.to_row``; nothing
here reads files.
"""
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json

from ..model import Cents, CompanyCode, Diagnostic, IsoDate, Month
from ..money import integer


class Side(StrEnum):
    BANK = "BANK"
    BOOK = "BOOK"


class Shape(StrEnum):
    ONE_TO_ONE = "ONE_TO_ONE"
    ONE_TO_MANY = "ONE_TO_MANY"
    MANY_TO_ONE = "MANY_TO_ONE"


class Category(StrEnum):
    BANK_FEE_NOT_BOOKED = "BANK_FEE_NOT_BOOKED"
    INTEREST_NOT_BOOKED = "INTEREST_NOT_BOOKED"
    LOAN_INTEREST_NOT_BOOKED = "LOAN_INTEREST_NOT_BOOKED"
    CARD_SETTLEMENT_NOT_BOOKED = "CARD_SETTLEMENT_NOT_BOOKED"
    DIRECT_DEBIT_NOT_BOOKED = "DIRECT_DEBIT_NOT_BOOKED"
    RETURNED_DIRECT_DEBIT = "RETURNED_DIRECT_DEBIT"
    FX_RATE_DIFFERENCE = "FX_RATE_DIFFERENCE"
    FACTORING_CHARGES_NOT_BOOKED = "FACTORING_CHARGES_NOT_BOOKED"
    POOLING_NOT_BOOKED = "POOLING_NOT_BOOKED"
    UNRECORDED_RECEIPT = "UNRECORDED_RECEIPT"
    BOOK_AMOUNT_ERROR = "BOOK_AMOUNT_ERROR"
    WRONG_BANK_ACCOUNT = "WRONG_BANK_ACCOUNT"
    BOOK_DUPLICATE = "BOOK_DUPLICATE"
    BANK_ERROR = "BANK_ERROR"
    OUTSTANDING_PAYMENT = "OUTSTANDING_PAYMENT"
    TRANSFER_IN_TRANSIT = "TRANSFER_IN_TRANSIT"
    PRIOR_PERIOD_BANK_ITEM = "PRIOR_PERIOD_BANK_ITEM"
    FX_REVALUATION = "FX_REVALUATION"


DIFFERENCE_CATEGORIES = frozenset({Category.FX_RATE_DIFFERENCE, Category.LOAN_INTEREST_NOT_BOOKED,
                                   Category.FACTORING_CHARGES_NOT_BOOKED, Category.BOOK_AMOUNT_ERROR})
NO_ADJUSTMENT = frozenset({Category.BANK_ERROR, Category.OUTSTANDING_PAYMENT, Category.TRANSFER_IN_TRANSIT,
                           Category.PRIOR_PERIOD_BANK_ITEM, Category.FX_REVALUATION})


@dataclass(frozen=True, slots=True)
class BankAccount:
    id: str
    company: CompanyCode
    gl_account: str
    currency: str
    statement_format: str


@dataclass(frozen=True, slots=True)
class StatementLine:
    """One statement movement. ``detail`` fields come from the original N43/CAMT/CSV file."""

    id: str
    account: str
    month: Month
    booking_date: IsoDate
    value_date: IsoDate
    amount: Cents
    currency: str
    text: str
    mandate: str | None = None
    invoice: str | None = None
    receipt: str | None = None
    motive: str | None = None
    reference: str | None = None


@dataclass(frozen=True, slots=True)
class Statement:
    account: str
    month: Month
    opening: Cents
    closing: Cents
    lines: tuple[StatementLine, ...]


@dataclass(frozen=True, slots=True)
class BookLine:
    """A 572 line of a recorded entry. ``doc_amount`` is signed, in the line's document currency."""

    id: str
    entry_id: str
    company: CompanyCode
    date: IsoDate
    amount: Cents
    doc_amount: Cents
    currency: str
    source: str
    reference: str
    text: str


@dataclass(frozen=True, slots=True)
class Difference:
    category: Category
    amount: Cents
    """Bank minus book, in the account's currency; zero for factoring (no 572 effect)."""


@dataclass(frozen=True, slots=True)
class Match:
    bank_lines: tuple[str, ...]
    book_lines: tuple[str, ...]
    shape: Shape
    tier: str
    difference: Difference | None = None


@dataclass(frozen=True, slots=True)
class Unmatched:
    line_id: str
    side: Side
    category: Category
    amount: Cents


@dataclass(frozen=True, slots=True)
class AdjustmentLine:
    company: CompanyCode
    account: str
    debit: Cents
    credit: Cents
    partner: str | None = None
    assignment: str | None = None
    cost_center: str | None = None

    def __post_init__(self) -> None:
        integer(self.debit)
        integer(self.credit)
        if self.debit < 0 or self.credit < 0 or (self.debit and self.credit):
            raise ValueError("an adjustment line is a non-negative debit or credit")


@dataclass(frozen=True, slots=True)
class Adjustment:
    category: Category
    lines: tuple[AdjustmentLine, ...]
    causes: tuple[str, ...]
    """Ids of the statement or book lines that justify the entry."""

    def __post_init__(self) -> None:
        if not self.causes or len(set(self.causes)) != len(self.causes):
            raise ValueError("adjustment requires unique source causes")
        if len({line.company for line in self.lines}) != 1:
            raise ValueError("adjustment requires exactly one company")
        if self.category in NO_ADJUSTMENT:
            raise ValueError("this category must not generate an adjustment")
        if sum(line.debit for line in self.lines) != sum(line.credit for line in self.lines):
            raise ValueError("adjustment must balance")

    @property
    def owner(self) -> tuple[str, str]:
        """Stable ledger owner; cash application is a later, distinct stage."""
        event = self.causes[0] if len(self.causes) == 1 else "bankrec:" + hashlib.sha256(
            json.dumps(sorted(self.causes), separators=(",", ":")).encode()).hexdigest()
        stage = "bank_import" if self.category is Category.UNRECORDED_RECEIPT else "bank_rec"
        return event, stage


@dataclass(frozen=True, slots=True)
class AccountReconciliation:
    account: BankAccount
    month: Month
    statement_opening: Cents
    statement_closing: Cents
    book_balance: Cents
    matches: tuple[Match, ...]
    unmatched_bank: tuple[Unmatched, ...]
    unmatched_book: tuple[Unmatched, ...]
    adjustments: tuple[Adjustment, ...]
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True, slots=True)
class Unresolved:
    account: str
    reasons: tuple[Diagnostic, ...]


@dataclass(frozen=True, slots=True)
class BankRecRun:
    results: tuple[AccountReconciliation, ...]
    unresolved: tuple[Unresolved, ...] = field(default=())
