from typing import NamedTuple

from .scalars import AccountCode, CompanyCode


class BalanceKey(NamedTuple):
    """Key of a trial-balance row: one account of one company.

    It is the grain at which the closing trial balance is compared with the reference
    (``trial_balance_recorded``): per company, per account, nothing finer. A plain
    ``(company, account)`` tuple is equal and hashes identically, so
    ``balances()[("1100", "57200001")]`` keeps working.

    The balance is ``debit - credit`` in local-currency cents: assets and expenses are
    positive, liabilities and income negative. Companies are never added together
    (3100 reports in MXN, the rest in EUR).
    """

    company: CompanyCode
    account: AccountCode
