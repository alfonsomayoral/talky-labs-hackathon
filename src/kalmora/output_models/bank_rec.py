from typing import Required, TypedDict

from ..model.journal_line import JournalLine
from ..model.scalars import CompanyCode


class BankMatch(TypedDict):
    """Bank lines settled against book lines. The scorer compares every (bank, book) pair."""

    bank_lines: list[str]
    """Statement line ids from ``bank/<account>/<month>.lines.jsonl``."""

    book_lines: list[str]
    """``<entry id>#<line number>`` references into ``erp/journal_entries.jsonl``."""


class BankUnmatchedBank(TypedDict):
    bank_line: str
    category: str
    """Policy §4 category, e.g. ``BANK_FEE_NOT_BOOKED``."""


class BankUnmatchedBook(TypedDict):
    book_line: str
    category: str


class BankAdjustment(TypedDict, total=False):
    category: Required[str]
    lines: Required[list[JournalLine]]


class BankRecRow(TypedDict, total=False):
    """One row of ``bank_rec.jsonl``: the reconciliation of one account of ``tasks/bank_accounts.json``.

    Exactly one row per account.
    """

    account: Required[str]
    """Bank account id, e.g. ``BIN-1100``."""

    company: Required[CompanyCode]
    matches: Required[list[BankMatch]]
    unmatched_bank: Required[list[BankUnmatchedBank]]
    unmatched_book: Required[list[BankUnmatchedBook]]
    adjustments: Required[list[BankAdjustment]]
