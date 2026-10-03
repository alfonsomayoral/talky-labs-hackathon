from typing import Literal, Required, TypedDict

from ..model.journal_entry import JournalEntry
from ..model.scalars import Cents, CompanyCode, PartnerCode

CloseType = Literal["ACCRUAL", "PREPAID", "FX_REVAL", "BAD_DEBT", "WIP_REVENUE", "DOUBTFUL_RECLASS"]


class CloseRow(TypedDict, total=False):
    """One row of ``close.jsonl``: one closing item (month-end adjustment).

    The scorer groups rows by a key made of ``type``, ``company`` and one identity field that
    depends on the type: ``vendor`` for ACCRUAL, ``invoice`` for PREPAID, ``item`` for
    FX_REVAL (``AP:<doc_id>``, ``GL:<account>`` or ``BANK:<account>``), ``customer`` for
    BAD_DEBT and ``billing_item`` for WIP_REVENUE. Rows with the same key add up. Entries are
    dated the last day of the month; their day-1 reversals are not delivered.
    """

    type: Required[CloseType]
    company: Required[CompanyCode]
    amount: Required[Cents]
    vendor: PartnerCode
    invoice: str
    item: str
    customer: PartnerCode
    billing_item: str
    journal_entry: Required[JournalEntry]
