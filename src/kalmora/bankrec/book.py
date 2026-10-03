"""Book side: the 572 lines of the recorded journal for each bank account."""
from collections import defaultdict
from typing import Iterable

from ..data import PhaseData
from ..model import JournalEntry, Month
from ..money import company_local_currency
from .model import BankAccount, BookLine


def load_book(data: PhaseData, accounts: Iterable[BankAccount], first_month: Month, last_date: str = "9999-12-31"
              ) -> tuple[dict[str, list[BookLine]], dict[str, JournalEntry], dict[str, int]]:
    """572 lines posted from ``first_month`` up to ``last_date`` per account id, their entries, and the
    book balance (statement currency) accumulated before ``first_month``."""
    by_key = {(a.company, a.gl_account): a for a in accounts}
    lines: dict[str, list[BookLine]] = defaultdict(list)
    entries: dict[str, JournalEntry] = {}
    before: dict[str, int] = defaultdict(int)
    start = f"{first_month}-01"
    for entry in data.iter_journal():
        if entry["posting_date"] > last_date:
            continue
        for line in entry["lines"]:
            account = by_key.get((entry["company"], line["account"]))
            if account is None:
                continue
            amount = line["debit"] - line["credit"]
            sign = 1 if amount >= 0 else -1
            doc = line.get("amount_doc")
            local = company_local_currency(entry["company"])
            doc_amount = sign * doc if isinstance(doc, int) and doc else amount
            if entry.get("source", "").startswith("CLOSE_FX") and account.currency != local:
                doc_amount = 0  # a revaluation is not a movement in the account's own currency
            if entry["posting_date"] < start:
                before[account.id] += amount if account.currency == local else doc_amount
                continue
            lines[account.id].append(BookLine(
                id=f"{entry['id']}#{line['line']}", entry_id=entry["id"], company=entry["company"],
                date=entry["posting_date"], amount=amount, doc_amount=doc_amount,
                currency=line.get("currency") or entry.get("currency") or local,
                source=entry.get("source", ""), reference=entry.get("reference") or "",
                text=line.get("text") or entry.get("header_text") or ""))
            entries[entry["id"]] = entry
    return dict(lines), entries, dict(before)


def comparable(account: BankAccount, line: BookLine) -> int:
    """Book amount in the statement's currency: the document amount for a foreign-currency account."""
    return line.amount if account.currency == company_local_currency(account.company) else line.doc_amount
