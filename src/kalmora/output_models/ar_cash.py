from typing import Literal, Required, TypedDict

from ..model.journal_line import JournalLine
from ..model.scalars import Cents, PartnerCode

ResidualType = Literal["PENALTY", "NETTING_AP", "OVERPAYMENT_DUPLICATE", "FACTORED_MISDIRECTED", "NON_CUSTOMER"]


class ArApplication(TypedDict, total=False):
    """Part of a receipt applied to one document: an ``invoice`` or, for a promissory-note
    payment at maturity, a ``pagare``. The scorer matches ``(reference, amount)``."""

    invoice: str
    pagare: str
    amount: Required[Cents]


class ArResidual(TypedDict, total=False):
    """Difference between the receipt and its applications, classified by cause."""

    type: Required[ResidualType]
    invoice: str
    amount: Required[Cents]


class ArCashRow(TypedDict, total=False):
    """One row of ``ar_cash.jsonl``: the application of one bank line of ``tasks/ar_receipts.json``.

    Exactly one row per ``bank_line``. ``adjustment`` lines each carry their ``company``.
    """

    bank_line: Required[str]
    customer: Required[PartnerCode | None]
    """``None`` when the receipt does not come from a customer."""

    applications: Required[list[ArApplication]]
    residuals: Required[list[ArResidual]]
    adjustment: Required[list[JournalLine]]
    """Journal lines that apply the receipt (typically Dr 555 / Cr 430)."""
