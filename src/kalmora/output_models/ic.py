from typing import Required, TypedDict

from ..model.journal_line import JournalLine
from ..model.scalars import Cents, CompanyCode


class IcRow(TypedDict, total=False):
    """One row of ``ic.jsonl``: one intercompany difference found.

    The scorer identifies a row by ``(sorted pair, cause)``. ``adjustment`` lines each carry
    their ``company``; the responsible company books the correction.
    """

    pair: Required[list[CompanyCode]]
    """The two companies whose balances differ."""

    cause: Required[str]
    """Cause code, e.g. ``INTEREST_DAY_COUNT``."""

    amount: Cents
    responsible: CompanyCode
    adjustment: Required[list[JournalLine]]
