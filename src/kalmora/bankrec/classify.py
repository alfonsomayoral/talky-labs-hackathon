"""Categories for what stays unmatched (policy §4), from statement and book evidence only.

Bank side (text patterns on the statement, details from the original file) and book side
(source, timing and duplicate evidence). A line no rule recognises gets no category and a
diagnostic: nothing is guessed.
"""
import re
from collections import defaultdict

from ..model import Month
from .match import MatchState, days
from .model import BankAccount, BookLine, Category, Match, StatementLine
from .book import comparable

LATE_MONTH_DAYS = 6
"""A payment posted in the last days of the month with no statement line is an outstanding payment."""


def bank_category(line: StatementLine) -> Category | None:
    text = line.text.upper()
    if text.startswith(("COMISION DEVOLUCION", "DEVOLUCION RECIBO")):
        return Category.RETURNED_DIRECT_DEBIT
    if text.startswith(("COMISION", "GASTOS")):
        return Category.BANK_FEE_NOT_BOOKED
    if text.startswith("RECIBO ") and line.mandate and line.invoice:
        return Category.DIRECT_DEBIT_NOT_BOOKED
    if "INTERESES" in text and text.startswith(("ABONO LIQUIDACION", "RETENCION")):
        return Category.INTEREST_NOT_BOOKED
    if text.startswith("LIQUIDACION TARJETA"):
        return Category.CARD_SETTLEMENT_NOT_BOOKED
    if text.startswith("TRASPASO CASH POOLING"):
        return Category.POOLING_NOT_BOOKED
    if line.amount > 0 and text.startswith("TRANSFERENCIA DE"):
        return Category.UNRECORDED_RECEIPT
    return None


def duplicate_bank_lines(history: list[StatementLine]) -> set[str]:
    """Later occurrences of the same mandate + invoice + amount: the bank charged twice."""
    seen: set[tuple] = set()
    duplicates: set[str] = set()
    for line in sorted(history, key=lambda x: (x.booking_date, x.id)):
        if line.mandate and line.invoice:
            key = (line.mandate, line.invoice, line.amount)
            if key in seen:
                duplicates.add(line.id)
            seen.add(key)
    return duplicates


DUPLICATE_WINDOW_DAYS = 3


def duplicate_book_lines(lines: list[BookLine]) -> set[str]:
    """Later postings of the same reference, source and amount within a few days of an earlier original."""
    originals: dict[tuple, list[BookLine]] = defaultdict(list)
    duplicates: set[str] = set()
    for line in sorted(lines, key=lambda x: (x.date, x.id)):
        if not line.reference or line.source in ("BANKFEE", "CARD", "BANKINT"):
            continue
        key = (line.reference, line.source, line.amount)
        if any(days(o.date, line.date) <= DUPLICATE_WINDOW_DAYS for o in originals[key]):
            duplicates.add(line.id)
        else:
            originals[key].append(line)
    return duplicates


def book_category(line: BookLine, month_end: str) -> Category | None:
    if line.source.startswith("CLOSE_FX"):
        return Category.FX_REVALUATION
    if line.source == "TREASURY":
        return Category.TRANSFER_IN_TRANSIT
    if line.amount < 0 and days(line.date, month_end) <= LATE_MONTH_DAYS:
        return Category.OUTSTANDING_PAYMENT
    return None


def prior_period(state: MatchState, month: Month, book_by_id: dict[str, BookLine],
                 bank_by_id: dict[str, StatementLine]) -> tuple[list[Match], list[Match], list[Match]]:
    """Split matches into (this month, prior-period items, older)."""
    current, prior, older = [], [], []
    for match in state.matches:
        months = {bank_by_id[b].month for b in match.bank_lines}
        posted = {book_by_id[k].date[:7] for k in match.book_lines}
        if month in months:
            current.append(match)
        elif max(months) < month and month in posted:
            prior.append(match)
        else:
            older.append(match)
    return current, prior, older


def wrong_bank_pairs(states: dict[str, MatchState], accounts: dict[str, BankAccount], month: Month
                     ) -> list[tuple[str, StatementLine, str, BookLine]]:
    """(bank account, statement line, book account, book line) for same-company cross-account items.

    Evidence required: the statement line's reference token equals the book line's reference
    (payroll month, remittance, pooling date), the same amount and the same direction.
    """
    from .match import _group_keys
    found = []
    by_company: dict[str, list[str]] = defaultdict(list)
    for key, account in accounts.items():
        by_company[account.company].append(key)
    for keys in by_company.values():
        for a in keys:
            for line in [l for l in states[a].bank.values() if l.month == month]:
                tokens = {token for _, token in _group_keys(line, accounts[a])}
                for b in keys:
                    if b == a:
                        continue
                    for r in states[b].book.values():
                        if (r.date[:7] == month and comparable(accounts[b], r) == line.amount
                                and r.reference and r.reference in tokens):
                            found.append((a, line, b, r))
    taken_bank, taken_book, unique = set(), set(), []
    for a, line, b, r in sorted(found, key=lambda x: (x[1].id, x[3].id)):
        if line.id not in taken_bank and r.id not in taken_book:
            taken_bank.add(line.id)
            taken_book.add(r.id)
            unique.append((a, line, b, r))
    return unique


def month_end(month: Month) -> str:
    from calendar import monthrange
    year, number = int(month[:4]), int(month[5:])
    return f"{month}-{monthrange(year, number)[1]:02d}"
