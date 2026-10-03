"""Matching of statement lines with book lines of one account (policy §4).

Tiers, each using only evidence present in the data, in this order: reference groups
(remittance, payroll, confirming, SEPA, factoring, pooling), direct debits by invoice number,
foreign transfers by beneficiary, loan instalments, then exact amount with source-specific
timing. Months are processed chronologically so a month-end fee entry is never taken by the
following month's statement line. Nothing is matched by subset-sum search.
"""
import difflib
import re
import unicodedata
from collections import defaultdict
from datetime import date

from .book import comparable
from .model import (BankAccount, BookLine, Category, Difference, Match, Shape, StatementLine)

MONTH_END_SOURCES = frozenset({"BANKFEE", "CARD", "BANKINT"})
"""Entries posted at month end for that month's bank charges: match within the same month only."""
DD_LAG_DAYS = 35
"""A direct debit may be booked up to this many days after the bank executed it (prior-period items)."""
WINDOW_DAYS = 6
FX_TOLERANCE_BP = 200
"""A foreign transfer differs from its payment entry by at most 2 % (exchange-rate difference)."""


def _norm(text: str) -> str:
    folded = unicodedata.normalize("NFD", text.upper()).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Z0-9 ]", " ", folded).split())


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a)[:30], _norm(b)[:30]).ratio()


def days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days


class MatchState:
    """Unmatched lines and matches of one account while the tiers run."""

    def __init__(self, account: BankAccount, bank: list[StatementLine], book: list[BookLine]) -> None:
        self.account = account
        self.bank = {line.id: line for line in bank}
        self.bank_text = {line.id: line.text for line in bank}
        self.book = {line.id: line for line in book}
        self.matches: list[Match] = []
        self.diagnostics: list[str] = []

    def amount(self, line: BookLine) -> int:
        return comparable(self.account, line)

    def take(self, bank_ids: list[str], book_ids: list[str], tier: str, difference: Difference | None = None) -> None:
        shape = (Shape.ONE_TO_ONE if len(bank_ids) == len(book_ids) == 1
                 else Shape.ONE_TO_MANY if len(bank_ids) == 1 else Shape.MANY_TO_ONE)
        self.matches.append(Match(tuple(bank_ids), tuple(book_ids), shape, tier, difference))
        for key in bank_ids:
            del self.bank[key]
        for key in book_ids:
            del self.book[key]


def _group_keys(line: StatementLine, account: BankAccount) -> list[tuple[str, str]]:
    """(matching mode, token) pairs a statement line can use to find its book lines."""
    keys = []
    text = line.text.upper()
    if m := re.search(r"REMESA (\d{8}-\d{3})", text):
        keys.append(("suffix", m.group(1)))
    for pattern in (r"\b(CF\d{8,})", r"\b(SDD\d{6,})", r"\b(FAC\d{6,})"):
        if m := re.search(pattern, text):
            keys.append(("exact", m.group(1)))
    if m := re.search(r"ORDEN NOMINAS (\d\d)/(\d{4})", text):
        keys.append(("exact", f"NOM{m.group(2)}{m.group(1)}"))
    if "TRASPASO CASH POOLING" in text:
        suffix = re.search(r"POOLING (?:[A-Z]+-)?(\d{4})\b", text)
        company = suffix.group(1) if suffix else account.company
        keys.append(("exact", f"CP{line.booking_date[2:4]}{line.booking_date[5:7]}{line.booking_date[8:10]}{company}"))
    return keys


def _tier_groups(state: MatchState) -> None:
    bank_by_key: dict[tuple[str, str], list[StatementLine]] = defaultdict(list)
    for line in state.bank.values():
        for key in _group_keys(line, state.account):
            bank_by_key[key].append(line)
    for (mode, token), bank_lines in sorted(bank_by_key.items()):
        book_lines = [r for r in state.book.values()
                      if (r.reference.endswith(token) if mode == "suffix" else r.reference == token)]
        bank_lines = [b for b in bank_lines if b.id in state.bank]
        book_lines = [r for r in book_lines if any(abs(days(b.booking_date, r.date)) <= WINDOW_DAYS for b in bank_lines)]
        if not bank_lines or not book_lines:
            continue
        if sum(b.amount for b in bank_lines) == sum(state.amount(r) for r in book_lines):
            state.take([b.id for b in bank_lines], [r.id for r in book_lines], "reference-group")
        else:
            state.diagnostics.append(f"group {token}: totals differ, left unmatched")


def _tier_invoice(state: MatchState) -> None:
    for line in sorted(state.bank.values(), key=lambda x: (x.booking_date, x.id)):
        if not line.invoice or not line.mandate:
            continue
        same = [r for r in state.book.values() if r.source == "DD" and r.reference == line.invoice]
        exact = [r for r in same if state.amount(r) == line.amount]
        if len(exact) == 1:
            state.take([line.id], [exact[0].id], "direct-debit-invoice")
        elif not exact and len(same) == 1:
            diff = line.amount - state.amount(same[0])
            state.take([line.id], [same[0].id], "direct-debit-invoice",
                       Difference(Category.BOOK_AMOUNT_ERROR, diff))


def _beneficiary(text: str) -> str | None:
    m = re.match(r"TRANSF\. EXTERIOR [A-Z]{3} [\d., ]+ (.+)$", text.upper())
    return m.group(1) if m else None


def _tier_foreign(state: MatchState) -> None:
    for line in sorted(state.bank.values(), key=lambda x: (x.booking_date, x.id)):
        name = _beneficiary(line.text)
        if not name:
            continue
        options = []
        for r in state.book.values():
            if r.source != "SWIFT" or abs(days(line.booking_date, r.date)) > 3:
                continue
            book = state.amount(r)
            if book * line.amount <= 0 or abs(line.amount - book) * 10000 > FX_TOLERANCE_BP * abs(book):
                continue
            score = similarity(name, r.text.replace("Transferencia internacional", ""))
            if score >= 0.6:
                options.append((-score, r.id, r))
        if options:
            options.sort(key=lambda x: x[:2])
            target = options[0][2]
            gap = line.amount - state.amount(target)
            state.take([line.id], [target.id], "foreign-transfer",
                       Difference(Category.FX_RATE_DIFFERENCE, gap) if gap else None)


def _tier_loan(state: MatchState) -> None:
    for line in sorted(state.bank.values(), key=lambda x: (x.booking_date, x.id)):
        if not line.text.upper().startswith("CUOTA PRESTAMO"):
            continue
        options = [r for r in state.book.values() if r.source == "LOAN" and abs(days(line.booking_date, r.date)) <= WINDOW_DAYS
                   and state.amount(r) * line.amount > 0 and abs(line.amount) > abs(state.amount(r))]
        if len(options) == 1:
            state.take([line.id], [options[0].id], "loan-instalment",
                       Difference(Category.LOAN_INTEREST_NOT_BOOKED, line.amount - state.amount(options[0])))


def _allowed(bank: StatementLine, book: BookLine) -> bool:
    gap = days(bank.booking_date, book.date)
    if book.source in MONTH_END_SOURCES:
        return bank.booking_date[:7] == book.date[:7] and gap >= 0
    if book.source == "DD":
        return -WINDOW_DAYS <= gap <= DD_LAG_DAYS
    return abs(gap) <= WINDOW_DAYS


def _tier_amount(state: MatchState) -> None:
    by_amount: dict[int, list[BookLine]] = defaultdict(list)
    for r in state.book.values():
        by_amount[state.amount(r)].append(r)
    candidates = []
    for line in state.bank.values():
        for r in by_amount.get(line.amount, []):
            if _allowed(line, r):
                candidates.append((line.month, abs(days(line.booking_date, r.date)), -similarity(line.text, r.text), line.id, r.id))
    candidates.sort()
    for _, gap, neg, bank_id, book_id in candidates:
        if bank_id in state.bank and book_id in state.book:
            rivals = [c for c in candidates if c[3] == bank_id and c[:3] == (state.bank[bank_id].month, gap, neg) and c[4] in state.book]
            if len(rivals) > 1:
                state.diagnostics.append(f"ambiguous {bank_id}: {len(rivals)} equal candidates, paired in id order")
            state.take([bank_id], [book_id], "amount")


def match_account(account: BankAccount, bank: list[StatementLine], book: list[BookLine]) -> MatchState:
    """Run every tier; the returned state holds the matches and what is still unmatched."""
    state = MatchState(account, bank, book)
    for tier in (_tier_groups, _tier_invoice, _tier_foreign, _tier_loan, _tier_amount):
        tier(state)
    return state
