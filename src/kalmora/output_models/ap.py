from typing import Literal, NotRequired, Required, TypedDict

from ..model.journal_entry import JournalEntry
from ..model.scalars import AccountCode, Cents, CompanyCode, Currency, IsoDate, PartnerCode

DocumentType = Literal["INVOICE", "CREDIT_NOTE", "DOWN_PAYMENT_REQUEST", "PROFORMA", "VENDOR_STATEMENT",
                       "FACTORING_NOTICE", "TAX_GARNISHMENT_ORDER", "BANK_DETAILS_CHANGE",
                       "CONTRACTOR_TAX_CERTIFICATE"]
Decision = Literal["POST", "POST_PAYMENT_BLOCK", "HOLD", "REJECT", "DUPLICATE", "NOT_INVOICE"]
Action = Literal["NONE", "REGISTER_ALTERNATIVE_PAYEE", "REGISTER_EMBARGO", "UPDATE_BANK_DETAILS",
                 "UPDATE_CONTRACTOR_CERTIFICATE"]
PaymentBlock = Literal["CONTRACTOR_CERTIFICATE_EXPIRED"]


class ApPayee(TypedDict, total=False):
    """Alternative payee that replaces the vendor for payment."""

    type: Required[Literal["FACTOR", "AEAT_EMBARGO"]]
    """Kind of payee; the only field the scorer compares."""


class ApLine(TypedDict, total=False):
    """One coded invoice line; factual allocations may survive a non-posting decision."""

    amount: Required[Cents]
    """Net amount of the line in document currency, in cents (M0 convention)."""

    account: Required[AccountCode]
    cost_center: str | None
    wbs: str | None
    """Cost object; the golden never carries both on one line."""

    tax_code: Required[str]
    po: str | None
    """Purchase order number; the scorer matches ``(po, po_item)`` on lines that have one."""

    po_item: int | None


class ApRow(TypedDict, total=False):
    """One row of ``ap.jsonl``: the decision for one document of ``tasks/ap_documents.json``.

    Exactly one row per ``doc_id``. The header, ``lines`` and ``journal_entry`` are scored
    only for ``POST`` and ``POST_PAYMENT_BLOCK``; ``journal_entry`` exists only for those two
    decisions. Header and coded-line amounts are integer cents in document currency;
    journal-entry amounts are in local currency (see docs/discrepancies.md).
    """

    doc_id: Required[str]
    """Document identifier, e.g. ``API005263``."""

    document_type: Required[DocumentType]
    decision: Required[Decision]
    reasons: Required[list[str]]
    """Policy §2.2 reason codes (``PRICE_VARIANCE``...); empty when the decision needs none."""

    company: CompanyCode
    vendor_id: PartnerCode | None
    """``None`` when the vendor does not exist in the master."""

    invoice_number: str | None
    """Compared after removing punctuation and leading zeros."""

    invoice_date: IsoDate
    currency: Currency
    net: Cents
    tax: Cents
    gross: Cents
    withholding: Cents
    retention: Cents
    payable: Cents
    duplicate_of: str | None
    """``doc_id`` of the original, for ``DUPLICATE``."""

    payee: ApPayee | None
    payment_block: PaymentBlock | None
    action: NotRequired[Action]
    """Only for ``NOT_INVOICE``."""

    lines: list[ApLine]
    journal_entry: JournalEntry
    """Only for ``POST`` and ``POST_PAYMENT_BLOCK``."""
