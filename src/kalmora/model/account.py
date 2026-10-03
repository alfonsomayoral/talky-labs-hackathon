from typing import Literal, TypedDict

from .scalars import AccountCode


class Account(TypedDict):
    """Chart-of-accounts entry (``erp/chart_of_accounts.jsonl``)."""

    account: AccountCode
    description: str

    type: Literal["BS", "PL"]
    """``BS`` balance sheet (assets, liabilities, equity) carries its balance forward;
    ``PL`` profit and loss (expenses, income) is the result of the period."""

    open_items: bool
    """Whether the account is managed by open items: postings need a ``partner`` and are
    matched through ``assignment``. This is the *data* source of the rule;
    ``ledger.is_open_item_account`` is the prefix-based rule the code applies today."""
