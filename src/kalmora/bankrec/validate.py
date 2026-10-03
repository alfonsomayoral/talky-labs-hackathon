"""Golden-free checks on a reconciliation (policy §4 and the month-end identity).

``carry``: statement closing minus book balance at month end must equal the unmatched statement
lines plus the matched differences minus the unmatched book lines posted in the month (prior-period
items excluded, their statement line is in an earlier month). A non-zero carry means an item of an
earlier month is still open. ``after adjustments``: once the adjustments are posted, only
bank errors and the book items that need no adjustment may remain.
"""
from .model import Category, Unmatched

REMAINING_BOOK = frozenset({Category.OUTSTANDING_PAYMENT, Category.TRANSFER_IN_TRANSIT, Category.FX_REVALUATION})


def carry(closing: int, book_balance: int, unmatched_bank: list[int], differences: list[int],
          unmatched_book: list[Unmatched]) -> int:
    book = sum(u.amount for u in unmatched_book if u.category is not Category.PRIOR_PERIOD_BANK_ITEM)
    return (closing - book_balance) - (sum(unmatched_bank) + sum(differences) - book)


def after_adjustments(closing: int, book_balance: int, effect: int, bank_errors: int,
                      unmatched_book: list[Unmatched]) -> int:
    remaining = sum(u.amount for u in unmatched_book if u.category in REMAINING_BOOK)
    return (closing - (book_balance + effect)) - (bank_errors - remaining)
