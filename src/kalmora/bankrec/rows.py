"""Delivery rows (``FORMATO_ENTREGA.md``) from reconciliations."""
from ..model import JournalLine
from ..output_models import BankRecRow
from ..output_models.bank_rec import BankAdjustment, BankMatch, BankUnmatchedBank, BankUnmatchedBook
from .model import AccountReconciliation, AdjustmentLine


def _line(line: AdjustmentLine) -> JournalLine:
    row = JournalLine(account=line.account, debit=line.debit, credit=line.credit, company=line.company)
    for key in ("partner", "assignment", "cost_center"):
        value = getattr(line, key)
        if value is not None:
            row[key] = value  # type: ignore[literal-required]
    return row


def to_row(result: AccountReconciliation) -> BankRecRow:
    return BankRecRow(
        account=result.account.id, company=result.account.company,
        matches=[BankMatch(bank_lines=list(m.bank_lines), book_lines=list(m.book_lines)) for m in result.matches],
        unmatched_bank=[BankUnmatchedBank(bank_line=u.line_id, category=u.category.value) for u in result.unmatched_bank],
        unmatched_book=[BankUnmatchedBook(book_line=u.line_id, category=u.category.value) for u in result.unmatched_book],
        adjustments=[BankAdjustment(category=a.category.value, lines=[_line(x) for x in a.lines]) for a in result.adjustments])
