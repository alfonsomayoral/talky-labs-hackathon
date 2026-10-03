from typing import TypedDict

from .scalars import AccountCode, Cents, CompanyCode, PartnerCode


class OpenItem(TypedDict):
    """Row of ``erp/open_items.jsonl``: an open-item balance as the ERP reports it.

    It is a master snapshot supplied with the phase, not something recomputed from the
    journal. ``Ledger.open_items()`` produces the computed equivalent, indexed by
    ``OpenItemKey``, which is how a solver can check that the ERP master and the journal
    agree before deciding what to clear, accrue or revalue.
    """

    company: CompanyCode
    account: AccountCode
    partner: PartnerCode | None
    assignment: str | None

    balance: Cents
    """``debit - credit`` in local-currency cents. Negative on payables (what the company
    owes), positive on receivables. Zero would mean cleared and is normally not listed."""
