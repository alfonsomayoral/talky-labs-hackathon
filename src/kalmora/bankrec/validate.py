"""Golden-free checks on a reconciliation (policy §4 and the month-end identity).

``carry``: statement closing minus book balance at month end must equal the unmatched statement
lines plus the matched differences minus the unmatched book lines posted in the month (prior-period
items excluded, their statement line is in an earlier month). A non-zero carry means an item of an
earlier month is still open. ``after adjustments``: once the adjustments are posted, only
bank errors and the book items that need no adjustment may remain.
"""
from collections import Counter
from .book import comparable
from .model import (AccountReconciliation, BookLine, Category, DIFFERENCE_CATEGORIES, Shape, Side,
                    Statement, StatementLine, Unmatched)

REMAINING_BOOK = frozenset({Category.OUTSTANDING_PAYMENT, Category.TRANSFER_IN_TRANSIT, Category.FX_REVALUATION})


def reconciliation(result: AccountReconciliation, statement: Statement,
                   banks: dict[str, StatementLine], books: dict[str, BookLine]) -> list[str]:
    """Coverage and accounting checks independent of reference labels or scorer."""
    errors, bank_used, book_used = [], [], []
    def problem(message):
        errors.append("validation: " + message)
    if (result.statement_opening, result.statement_closing) != (statement.opening, statement.closing):
        problem("statement balances differ from source")
    if statement.closing - statement.opening != sum(x.amount for x in statement.lines):
        problem("statement opening plus movements differs from closing")
    for x in statement.lines:
        if x.currency != result.account.currency or x.account != result.account.id:
            problem(f"{x.id}: statement account/currency differs")
    for match in result.matches:
        bank_used.extend(match.bank_lines)
        book_used.extend(match.book_lines)
        sizes = (len(match.bank_lines), len(match.book_lines))
        valid = {Shape.ONE_TO_ONE: sizes == (1, 1), Shape.ONE_TO_MANY: sizes[0] == 1 and sizes[1] > 1,
                 Shape.MANY_TO_ONE: sizes[0] > 1 and sizes[1] == 1}
        if not valid.get(match.shape):
            problem("match shape differs from references")
        if not set(match.bank_lines) <= banks.keys() or not set(match.book_lines) <= books.keys():
            problem("match references unknown source")
            continue
        difference = sum(banks[k].amount for k in match.bank_lines) - sum(comparable(result.account, books[k]) for k in match.book_lines)
        if match.difference:
            if match.difference.category not in DIFFERENCE_CATEGORIES or match.difference.amount != difference:
                problem("matched difference is unexplained or incorrect")
        elif difference:
            problem("unequal match has no explained difference")
    for unmatched, side, source, used in ((result.unmatched_bank, Side.BANK, banks, bank_used),
                                         (result.unmatched_book, Side.BOOK, books, book_used)):
        for u in unmatched:
            used.append(u.line_id)
            if u.side is not side or not isinstance(u.category, Category) or u.line_id not in source:
                problem("unmatched side/category/reference is invalid")
                continue
            amount = source[u.line_id].amount if side is Side.BANK else comparable(result.account, source[u.line_id])
            if amount != u.amount:
                problem("unmatched amount differs from source")
    if any(n > 1 for n in Counter(bank_used).values()) or any(n > 1 for n in Counter(book_used).values()):
        problem("source line reused")
    if set(bank_used) != {x.id for x in statement.lines}:
        problem("current statement coverage is incomplete or outside period")
    current_books = {x.id for x in books.values() if x.company == result.account.company
                     and x.date[:7] == result.month}
    # The runner passes the account's books separately; wrong-bank adjustment
    # causes may point to another account, but they are not matches of this one.
    if not current_books <= set(book_used):
        problem("current book coverage is incomplete")
    owners, causes = set(), set()
    known = set(bank_used) | set(book_used)
    for adjustment in result.adjustments:
        if adjustment.owner in owners or causes.intersection(adjustment.causes):
            problem("adjustment owner or cause reused")
        owners.add(adjustment.owner)
        causes.update(adjustment.causes)
        if any(x.company != result.account.company for x in adjustment.lines):
            problem("adjustment society differs from account")
        # Wrong-account causes intentionally include a book line on the other account.
        if adjustment.category is not Category.WRONG_BANK_ACCOUNT and not set(adjustment.causes) <= known:
            problem("adjustment cause outside classified or matched lines")
    return errors


def carry(closing: int, book_balance: int, unmatched_bank: list[int], differences: list[int],
          unmatched_book: list[Unmatched]) -> int:
    book = sum(u.amount for u in unmatched_book if u.category is not Category.PRIOR_PERIOD_BANK_ITEM)
    return (closing - book_balance) - (sum(unmatched_bank) + sum(differences) - book)


def after_adjustments(closing: int, book_balance: int, effect: int, bank_errors: int,
                      unmatched_book: list[Unmatched]) -> int:
    remaining = sum(u.amount for u in unmatched_book if u.category in REMAINING_BOOK)
    return (closing - (book_balance + effect)) - (bank_errors - remaining)
