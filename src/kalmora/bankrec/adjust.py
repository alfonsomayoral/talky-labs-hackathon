"""Adjustment entries for the reconciling items that policy §4 says must be booked.

Shapes follow the historical entries of the same sources and the delivery conventions:
fees with equal account, date, concept and amount are one aggregated entry; a returned
receipt, an interest settlement and a duplicate payment are one entry each. Amounts are in
the company's functional currency; a foreign-currency statement amount is converted at the
SYN-BCE rate of the statement line's booking date.
"""
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable

from ..model import JournalEntry
from ..money import RateTable, company_local_currency
from .model import (Adjustment, AdjustmentLine, BankAccount, BookLine, Category, Difference, StatementLine)

FEE, GUARANTEE_FEE, RETENTION_TAX, INTEREST_INCOME = "62600000", "66900000", "47300000", "76200000"
CARD_EXPENSE, CARD_COST_CENTER = "62910000", "CC-1000-DIR"
VENDOR, CUSTOMER, POOLING, RECEIPTS = "41000000", "43000000", "55200000", "55500000"
FX_LOSS, FX_GAIN, LOAN_INTEREST, FACTORING_CHARGES, FACTOR = "66800000", "76800000", "66200000", "66500000", "55300000"
HEAD_COMPANY = "1000"
RETENTION_BP = 1900


@dataclass
class AdjustContext:
    rates: RateTable
    entries: dict[str, JournalEntry]
    factoring: dict[str, dict]
    receipt_customer: Callable[[str], str | None]
    # A direct debit is posted against its vendor invoice only when that invoice is posted in the
    # history or received in this month's AP inbox; otherwise AP has nothing to clear yet.
    invoice_known: Callable[[str, str | None], bool] = lambda vendor, invoice: True


class Builder:
    def __init__(self, account: BankAccount, ctx: AdjustContext) -> None:
        self.account, self.ctx = account, ctx
        self.local = company_local_currency(account.company)
        self.out: list[Adjustment] = []
        self.diagnostics: list[str] = []
        self.skipped_debits: set[str] = set()

    def local_amount(self, amount: int, line: StatementLine) -> int:
        """Absolute amount in functional currency."""
        value = abs(amount)
        if self.account.currency == self.local:
            return value
        return self.ctx.rates.convert_cents(value, self.account.currency, self.local, line.booking_date)

    def line(self, account: str, debit: int = 0, credit: int = 0, **extra: str | None) -> AdjustmentLine:
        return AdjustmentLine(self.account.company, account, debit, credit, **extra)  # type: ignore[arg-type]

    def add(self, category: Category, lines: list[AdjustmentLine], causes: list[str]) -> None:
        self.out.append(Adjustment(category, tuple(lines), tuple(causes)))

    def bank_side(self, line: StatementLine, amount: int) -> tuple[int, int]:
        """(debit, credit) of the 572 line for a statement amount: money in is a debit."""
        return (amount, 0) if line.amount > 0 else (0, amount)


def fees(b: Builder, lines: list[StatementLine]) -> None:
    groups: dict[tuple, list[StatementLine]] = defaultdict(list)
    for line in lines:
        groups[(line.booking_date, line.text, line.amount)].append(line)
    for (_, text, _), group in sorted(groups.items()):
        total = sum(b.local_amount(x.amount, x) for x in group)
        expense = GUARANTEE_FEE if "AVAL" in text.upper() else FEE
        b.add(Category.BANK_FEE_NOT_BOOKED, [b.line(expense, total), b.line(b.account.gl_account, credit=total)],
              [x.id for x in group])


def direct_debits(b: Builder, lines: list[StatementLine]) -> None:
    for x in lines:
        amount = b.local_amount(x.amount, x)
        vendor = (x.mandate or "").split("-")[0]
        if not b.ctx.invoice_known(vendor, x.invoice):
            b.skipped_debits.add(x.id)
            b.diagnostics.append(f"deferred direct debit {x.id}: invoice {x.invoice} is neither posted nor in the AP inbox")
            continue
        b.add(Category.DIRECT_DEBIT_NOT_BOOKED,
              [b.line(VENDOR, amount, partner=vendor, assignment=x.invoice), b.line(b.account.gl_account, credit=amount)],
              [x.id])


def returned(b: Builder, lines: list[StatementLine]) -> None:
    ordered = sorted(lines, key=lambda x: (x.booking_date, x.id))
    used_fees: set[str] = set()
    for index, x in enumerate(ordered):
        if not x.text.upper().startswith("DEVOLUCION RECIBO"):
            continue
        commission = next((c for c in ordered[index + 1:] if c.text.upper().startswith("COMISION DEVOLUCION")
                           and c.booking_date == x.booking_date and c.id not in used_fees), None)
        customer = b.ctx.receipt_customer(x.receipt) if x.receipt else None
        if not customer:
            b.diagnostics.append(f"{x.id}: returned receipt {x.receipt} has no customer; no entry built")
            continue
        debit_receipt = b.local_amount(x.amount, x)
        fee = b.local_amount(commission.amount, commission) if commission else 0
        rows = [b.line(CUSTOMER, debit_receipt, partner=customer, assignment=x.receipt)]
        if fee:
            rows.append(b.line(FEE, fee))
        rows.append(b.line(b.account.gl_account, credit=debit_receipt + fee))
        b.add(Category.RETURNED_DIRECT_DEBIT, rows, [x.id] + ([commission.id] if commission else []))
        if commission:
            used_fees.add(commission.id)


def interest(b: Builder, lines: list[StatementLine]) -> None:
    by_date: dict[str, list[StatementLine]] = defaultdict(list)
    for x in lines:
        by_date[x.booking_date].append(x)
    for day, group in sorted(by_date.items()):
        gross = next((x for x in group if x.amount > 0), None)
        tax = next((x for x in group if x.amount < 0), None)
        if gross is None:
            b.diagnostics.append(f"{day}: interest retention without the interest credit; no entry built")
            continue
        credit = b.local_amount(gross.amount, gross)
        withheld = b.local_amount(tax.amount, tax) if tax else 0
        if tax and abs(withheld * 10000 - credit * RETENTION_BP) > 5000:
            b.diagnostics.append(f"{day}: retention {withheld} is not 19 % of interest {credit}")
        rows = [b.line(b.account.gl_account, credit - withheld)]
        if withheld:
            rows.append(b.line(RETENTION_TAX, withheld))
        rows.append(b.line(INTEREST_INCOME, credit=credit))
        b.add(Category.INTEREST_NOT_BOOKED, rows, [x.id for x in group])


def card(b: Builder, lines: list[StatementLine]) -> None:
    for x in lines:
        amount = b.local_amount(x.amount, x)
        b.add(Category.CARD_SETTLEMENT_NOT_BOOKED,
              [b.line(CARD_EXPENSE, amount, cost_center=CARD_COST_CENTER), b.line(b.account.gl_account, credit=amount)], [x.id])


def pooling(b: Builder, lines: list[StatementLine]) -> None:
    import re
    for x in lines:
        amount = b.local_amount(x.amount, x)
        suffix = re.search(r"POOLING (?:[A-Z]+-)?(\d{4})\b", x.text.upper())
        partner = HEAD_COMPANY if b.account.company != HEAD_COMPANY else (suffix.group(1) if suffix else None)
        if partner is None:
            b.diagnostics.append(f"{x.id}: pooling counterpart unknown; no entry built")
            continue
        debit, credit = b.bank_side(x, amount)
        b.add(Category.POOLING_NOT_BOOKED, [b.line(b.account.gl_account, debit, credit),
                                           b.line(POOLING, credit, debit, partner=partner)], [x.id])


def unrecorded_receipts(b: Builder, lines: list[StatementLine]) -> None:
    for x in lines:
        amount = b.local_amount(x.amount, x)
        b.add(Category.UNRECORDED_RECEIPT, [b.line(b.account.gl_account, amount), b.line(RECEIPTS, credit=amount)], [x.id])


def _fx_account(entries: dict[str, JournalEntry], book: BookLine, shortfall: bool) -> str:
    entry = entries.get(book.entry_id)
    for entry_line in entry["lines"] if entry else []:
        if entry_line["account"] in (FX_LOSS, FX_GAIN):
            return entry_line["account"]
    return FX_LOSS if shortfall else FX_GAIN


def differences(b: Builder, items: list[tuple[StatementLine, BookLine, Difference]]) -> None:
    for line, book, diff in items:
        if diff.category is Category.FACTORING_CHARGES_NOT_BOOKED:
            row = b.ctx.factoring.get(book.reference)
            if row is None:
                continue
            charges = row["interest"] + row["fee"]
            b.add(diff.category, [b.line(FACTORING_CHARGES, charges),
                                  b.line(FACTOR, credit=charges, partner="FACTOR-BAE", assignment=row["invoice"])],
                  [line.id, book.id])
            continue
        amount = b.local_amount(diff.amount, line)
        paid_more = diff.amount < 0
        if diff.category is Category.FX_RATE_DIFFERENCE:
            fx = _fx_account(b.ctx.entries, book, paid_more)
            other = (b.line(fx, amount), b.line(b.account.gl_account, credit=amount)) if paid_more else \
                    (b.line(b.account.gl_account, amount), b.line(fx, credit=amount))
        elif diff.category is Category.LOAN_INTEREST_NOT_BOOKED:
            other = (b.line(LOAN_INTEREST, amount), b.line(b.account.gl_account, credit=amount)) if paid_more else \
                    (b.line(b.account.gl_account, amount), b.line(LOAN_INTEREST, credit=amount))
        else:  # BOOK_AMOUNT_ERROR: correct against the vendor of the direct debit
            vendor = (line.mandate or "").split("-")[0]
            other = (b.line(VENDOR, amount, partner=vendor, assignment=line.invoice), b.line(b.account.gl_account, credit=amount)) \
                if paid_more else (b.line(b.account.gl_account, amount), b.line(VENDOR, credit=amount, partner=vendor, assignment=line.invoice))
        b.add(diff.category, list(other), [line.id, book.id])


def book_duplicates(b: Builder, duplicates: list[BookLine]) -> None:
    for book in duplicates:
        entry = b.ctx.entries.get(book.entry_id)
        if entry is None:
            b.diagnostics.append(f"{book.id}: duplicate entry not available; no cancellation built")
            continue
        rows = [AdjustmentLine(entry["company"], x["account"], x["credit"], x["debit"], x.get("partner"),
                               x.get("assignment"), x.get("cost_center")) for x in entry["lines"]]
        b.add(Category.BOOK_DUPLICATE, rows, [book.id])


def wrong_bank(b: Builder, pairs: list[tuple[StatementLine, BookLine, BankAccount]]) -> None:
    for line, book, other in pairs:
        amount = abs(book.amount)
        rows = ([b.line(other.gl_account, amount), b.line(b.account.gl_account, credit=amount)] if book.amount < 0
                else [b.line(b.account.gl_account, amount), b.line(other.gl_account, credit=amount)])
        b.add(Category.WRONG_BANK_ACCOUNT, rows, [line.id, book.id])
