"""Bank reconciliation of every account of a phase: statements + recorded journal -> results.

Matching runs over all statement months in chronological order and the target month is
projected (ADR 0005): statement lines of the month, book lines posted in it, and earlier book
lines paired with one of its statement lines. A book line posted in the month whose statement
line is in an earlier month is reported as a prior-period item. Pure after the reads.
"""
from collections import defaultdict
import re

from ..data import PhaseData
from ..model import Month
from ..money import RateTable, company_local_currency
from . import adjust as adj
from . import classify, validate
from .book import comparable, load_book
from .match import MatchState, match_account
from .model import (AccountReconciliation, BankAccount, BankRecRun, BookLine, Category, DIFFERENCE_CATEGORIES, Difference,
                    Match, Shape, StatementLine, Unmatched, Unresolved, Side)
from .statements import StatementError, read_statements


def load_accounts(data: PhaseData) -> list[BankAccount]:
    """Accounts in ``tasks/bank_accounts.json`` order."""
    return [BankAccount(r["id"], r["company"], r["gl_account"], r["currency"], r["statement_format"])
            for r in (data.get("bank_accounts", account_id) for account_id in data.table("tasks/bank_accounts"))]


def _tag_factoring(state: MatchState, books: dict[str, BookLine], entries: dict, factoring: dict[str, dict]) -> None:
    """A factoring advance whose entry lacks the charges line is a match with a charges difference."""
    for index, match in enumerate(state.matches):
        if match.difference or len(match.book_lines) != 1:
            continue
        book = books[match.book_lines[0]]
        row = factoring.get(book.reference)
        bank = state.bank_text.get(match.bank_lines[0], "") if hasattr(state, "bank_text") else ""
        if book.source != "FACTORING" or row is None or "ANTICIPO" not in bank.upper():
            continue
        lines = entries.get(book.entry_id, {}).get("lines", [])
        if not any(x["account"] == adj.FACTORING_CHARGES and x["debit"] for x in lines):
            state.matches[index] = Match(match.bank_lines, match.book_lines, match.shape, match.tier,
                                         Difference(Category.FACTORING_CHARGES_NOT_BOOKED, 0))


_INBOX_INVOICE = re.compile(r"(?:factura|facturae|invoice|cfdi)_(.+)\.\w+$", re.IGNORECASE)
_SUBJECT_INVOICE = re.compile(r"(?:FRA|Factura)\s+(\S+)")


def _invoice_number(value: object) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(value or "").upper()).lstrip("0")


def known_invoices(data: PhaseData, ap_rows: list[dict] | None = None):
    """(vendor, invoice) -> True if the invoice is posted in the AP history, or posted by this month's AP
    delivery (``ap_rows``) or, without that delivery, named in this month's AP inbox.

    Without an AP history there is no evidence either way, so every direct debit keeps its adjustment."""
    try:
        history = data.table("ap_invoices")
    except KeyError:
        return lambda vendor, invoice: True
    posted = {(str(r["vendor"]), _invoice_number(r["number"])) for r in history
              if r.get("decision") in ("POST", "POST_PAYMENT_BLOCK")}
    if ap_rows is not None:
        posted |= {(str(r.get("vendor_id")), _invoice_number(r.get("invoice_number"))) for r in ap_rows
                   if r.get("decision") in ("POST", "POST_PAYMENT_BLOCK")}
        return lambda vendor, invoice: (vendor, _invoice_number(invoice)) in posted
    inbox: set[str] = set()
    for message in data.table("document_messages"):
        for attachment in message.get("attachments", []):
            if found := _INBOX_INVOICE.match(str(attachment)):
                inbox.add(_invoice_number(found.group(1)))
        inbox.update(_invoice_number(n) for n in _SUBJECT_INVOICE.findall(str(message.get("subject") or "")))

    def known(vendor: str, invoice: str | None) -> bool:
        number = _invoice_number(invoice)
        return bool(number) and ((vendor, number) in posted or number in inbox)
    return known


def build_bank_rec(data: PhaseData, month: Month | None = None, ap_rows: list[dict] | None = None) -> BankRecRun:
    month = month or data.month
    accounts = load_accounts(data)
    by_id = {a.id: a for a in accounts}
    statements, unresolved = {}, []
    for account in accounts:
        try:
            statements[account.id] = read_statements(data, account, month)
        except (StatementError, FileNotFoundError, KeyError) as error:
            unresolved.append(Unresolved(account.id, (f"statements: {error}",)))
    live = [a for a in accounts if a.id in statements]
    if not live:
        return BankRecRun((), tuple(unresolved))
    first = min(s.month for a in live for s in statements[a.id][:1])
    month_start, month_end = f"{month}-01", classify.month_end(month)
    book, entries, before = load_book(data, live, first, month_end)
    rates = RateTable(data.table("fx_rates"))
    factoring = {r["remittance"]: r for r in data.table("factoring_assignments")}

    def receipt_customer(receipt: str) -> str | None:
        try:
            return data.get("ar_invoices", receipt)["customer"]
        except (KeyError, ValueError):
            return None

    ctx = adj.AdjustContext(rates, entries, factoring, receipt_customer, known_invoices(data, ap_rows))
    bank_all = {a.id: [l for s in statements[a.id] for l in s.lines] for a in live}
    states = {a.id: match_account(a, bank_all[a.id], book.get(a.id, [])) for a in live}
    book_by_id = {a.id: {r.id: r for r in book.get(a.id, [])} for a in live}
    for a in live:
        _tag_factoring(states[a.id], book_by_id[a.id], entries, factoring)
    pairs = classify.wrong_bank_pairs(states, {a.id: a for a in live}, month)
    wrong_bank_ids = {line.id for _, line, _, _ in pairs} | {r.id for _, _, _, r in pairs}

    built: dict[str, dict] = {}
    for a in live:
        state, bank_by_id, books = states[a.id], {l.id: l for l in bank_all[a.id]}, book_by_id[a.id]
        current, prior, _ = classify.prior_period(state, month, books, bank_by_id)
        diagnostics = list(state.diagnostics)
        bank_dups = classify.duplicate_bank_lines(bank_all[a.id])
        book_dups = classify.duplicate_book_lines(list(books.values()))
        unmatched_bank, by_category = [], defaultdict(list)
        category: Category | None
        for line in sorted((l for l in state.bank.values() if l.month == month), key=lambda x: (x.booking_date, x.id)):
            if line.id in wrong_bank_ids:
                category = Category.WRONG_BANK_ACCOUNT
            elif line.id in bank_dups:
                category = Category.BANK_ERROR
            else:
                category = classify.bank_category(line)
            if category is None:
                diagnostics.append(f"{line.id}: no rule recognises '{line.text}'; left out of the result")
                continue
            unmatched_bank.append(Unmatched(line.id, Side.BANK, category, line.amount))
            by_category[category].append(line)
        unmatched_book = []
        for r in sorted(state.book.values(), key=lambda x: (x.date, x.id)):
            if r.date < month_start or r.date > month_end:
                continue
            if r.id in wrong_bank_ids:
                category = Category.WRONG_BANK_ACCOUNT
            elif r.id in book_dups:
                category = Category.BOOK_DUPLICATE
            else:
                category = classify.book_category(r, month_end)
            if category is None:
                diagnostics.append(f"{r.id}: no rule recognises this unmatched book line; left out of the result")
                continue
            unmatched_book.append(Unmatched(r.id, Side.BOOK, category, comparable(a, r)))
        for match in prior:
            for key in match.book_lines:
                if books[key].date >= month_start:
                    unmatched_book.append(Unmatched(key, Side.BOOK, Category.PRIOR_PERIOD_BANK_ITEM, comparable(a, books[key])))
        builder = adj.Builder(a, ctx)
        adj.fees(builder, by_category[Category.BANK_FEE_NOT_BOOKED])
        adj.direct_debits(builder, by_category[Category.DIRECT_DEBIT_NOT_BOOKED])
        adj.returned(builder, by_category[Category.RETURNED_DIRECT_DEBIT])
        adj.interest(builder, by_category[Category.INTEREST_NOT_BOOKED])
        adj.card(builder, by_category[Category.CARD_SETTLEMENT_NOT_BOOKED])
        adj.pooling(builder, by_category[Category.POOLING_NOT_BOOKED])
        adj.unrecorded_receipts(builder, by_category[Category.UNRECORDED_RECEIPT])
        adj.differences(builder, [(bank_by_id[m.bank_lines[0]], books[m.book_lines[0]], m.difference)
                                  for m in current if m.difference and len(m.bank_lines) == len(m.book_lines) == 1])
        adj.book_duplicates(builder, [books[u.line_id] for u in unmatched_book if u.category is Category.BOOK_DUPLICATE])
        adj.wrong_bank(builder, [(line, r, by_id[b]) for acc, line, b, r in pairs if acc == a.id])
        diagnostics.extend(builder.diagnostics)
        built[a.id] = dict(current=current, unmatched_bank=unmatched_bank, unmatched_book=unmatched_book,
                           adjustments=builder.out, diagnostics=diagnostics, books=books, bank_by_id=bank_by_id,
                           deferred=builder.skipped_debits)

    results = []
    for a in live:
        b = built[a.id]
        closing = statements[a.id][-1].closing
        balance = before.get(a.id, 0) + sum(comparable(a, r) for r in book.get(a.id, []) if r.date <= month_end)
        diffs = [m.difference.amount for m in states[a.id].matches if m.difference]
        diagnostics = b["diagnostics"]
        carried = validate.carry(closing, balance, [u.amount for u in b["unmatched_bank"]], diffs, b["unmatched_book"])
        if carried:
            diagnostics.append(f"identity: carry-over of {carried} from items outside {month}")
        if a.currency == company_local_currency(a.company):
            effect = sum(x.debit - x.credit for r in live if r.company == a.company for ad in built[r.id]["adjustments"]
                         for x in ad.lines if x.account == a.gl_account and x.company == a.company)
            # Bank errors and deferred direct debits stay on the statement without an adjustment.
            errors = sum(u.amount for u in b["unmatched_bank"]
                         if u.category is Category.BANK_ERROR or u.line_id in b["deferred"])
            left = validate.after_adjustments(closing, balance, effect, errors, b["unmatched_book"])
            if left:
                diagnostics.append(f"identity: {left} unexplained after adjustments")
        result = AccountReconciliation(
            a, month, statements[a.id][-1].opening, closing, balance,
            tuple(m for m in b["current"] if not (len(m.bank_lines) == 0)), tuple(b["unmatched_bank"]),
            tuple(b["unmatched_book"]), tuple(b["adjustments"]), tuple(diagnostics))
        problems = validate.reconciliation(result, statements[a.id][-1], b["bank_by_id"], b["books"])
        if problems:
            from dataclasses import replace
            result = replace(result, diagnostics=result.diagnostics + tuple(problems))
        results.append(result)
    order = {a.id: i for i, a in enumerate(accounts)}
    return BankRecRun(tuple(sorted(results, key=lambda r: order[r.account.id])), tuple(unresolved))
