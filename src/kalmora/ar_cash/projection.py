"""Recorded + bank reconciliation + cash applications for downstream close.

This is an M3/M4 projection, not a completed period close. Unresolved receipts
remain in suspense and are exposed explicitly. No source journal is re-posted.
"""
from dataclasses import dataclass

from ..bankrec import journal_entries as bank_entries
from ..bankrec.model import BankRecRun
from ..data import PhaseData
from ..ledger import Ledger
from .engine import ArCashRun, _task_ids
from .journal import journal_entries


@dataclass(frozen=True)
class CashProjection:
    recorded: Ledger
    projected: Ledger
    unresolved: tuple[str, ...]

    @property
    def complete(self) -> bool:
        return not self.unresolved


def project_cash(data: PhaseData, cash: ArCashRun, bank: BankRecRun) -> CashProjection:
    """Publish independent books and explicit coverage; reject repeated owners.

    All application adjustment lines survive, including 431 notes, 438 advances,
    553 factoring and 565 guarantee returns. Partial payments retain their open
    balance. Neither applications nor residuals are posted a second time.
    """
    actual = [str(result.row["bank_line"]) for result in cash.results]
    if len(actual) != len(set(actual)) or set(actual) != set(_task_ids(data)):
        raise ValueError("cash projection requires exactly one result per receipt task")
    recorded = Ledger.from_entries(entry for entry in data.iter_journal()
                                   if str(entry["posting_date"])[:7] <= data.month)
    projected = recorded.project()
    for entry in (*bank_entries(bank), *journal_entries(data, cash)):
        projected.add_entry(entry, **entry['provenance'])
    unresolved = tuple(str(result.row['bank_line']) for result in cash.results
                       if not result.row['adjustment'])
    return CashProjection(recorded, projected, unresolved)


def projection_report(projection: CashProjection) -> dict:
    """JSON-ready balances/open items with recorded, adjustment and projected cents."""
    def rows(before, after, fields):
        return [dict(zip(fields, key), recorded=before.get(key, 0),
                     adjustment=after.get(key, 0)-before.get(key, 0), projected=after.get(key, 0))
                for key in sorted(before.keys() | after.keys(), key=lambda k: tuple(x or '' for x in k))]
    return {
        'scope': 'bank_rec_and_ar_cash', 'complete': projection.complete,
        'unresolved_receipts': list(projection.unresolved),
        'balances': rows(projection.recorded.balances(), projection.projected.balances(),
                         ('company', 'account')),
        'open_items': rows(projection.recorded.open_items(), projection.projected.open_items(),
                           ('company', 'account', 'partner', 'assignment')),
        'adjustments': projection.projected.entries[len(projection.recorded.entries):],
    }
